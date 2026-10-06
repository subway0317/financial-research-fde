import json

import pytest

from financial_research.agent.errors import GroundingValidationError
from financial_research.agent.evidence_projection import project_evidence
from financial_research.agent.grounding import validate_final_answer
from financial_research.agent.service import ResearchAgent
from financial_research.evals.dataset import DEFAULT_ROOT, load_suite
from financial_research.evals.fixtures import fixture_registry, load_fixtures
from financial_research.evals.judge import ClaimSupportJudge, SemanticEvaluationError, judge_payload
from financial_research.evals.offline import offline_agent_client
from financial_research.evals.support import support_for_answer
from financial_research.llm.errors import LLMProviderError
from financial_research.llm.fake import FakeLLMClient
from financial_research.schemas.agent import ClaimType, ResearchAgentRequest


@pytest.fixture
def answer():
    case = next(c for c in load_suite()[0].cases if c.case_id == "routing-fundamental_focus-en")
    return ResearchAgent(
        registry=fixture_registry(load_fixtures(DEFAULT_ROOT)[case.fixture_scenario]),
        llm=offline_agent_client(case),
    ).run(
        ResearchAgentRequest(question=case.question, ticker=case.ticker, as_of_date=case.as_of_date)
    )


@pytest.mark.parametrize(
    "verdict,severity,reason",
    [
        ("SUPPORTED", "LOW", "DIRECT_EVIDENCE_SUPPORT"),
        ("CONTRADICTED", "HIGH", "EVIDENCE_CONTRADICTION"),
        ("INSUFFICIENT", "MEDIUM", "INSUFFICIENT_EVIDENCE"),
    ],
)
def test_judge_preserves_typed_claim_level_verdicts_without_reasoning(
    answer, verdict, severity, reason
):
    claim = answer.claims[0]
    output = {
        "evaluations": [
            {
                "claim_id": claim.claim_id,
                "verdict": verdict,
                "severity": severity,
                "reason_code": reason,
                "evidence_ids": claim.evidence_ids,
            }
        ]
    }
    client = FakeLLMClient([json.dumps(output)])
    evaluations, usage = ClaimSupportJudge(client).evaluate(answer)
    assert (evaluations[0].verdict, evaluations[0].severity) == (verdict, severity)
    assert len(usage) == 1 and client.call_count == 1
    payload = json.loads(client.requests[0].user_payload)
    assert set(payload) == {"claims", "support_index", "support_projection_version"}
    assert "question" not in payload
    assert "reasoning" not in json.dumps(output)


@pytest.mark.parametrize(
    "change", ["unknown-claim", "unknown-evidence", "duplicate", "extra-reasoning", "bad-reason"]
)
def test_judge_rejects_incomplete_or_untraceable_structured_verdicts(answer, change):
    claim = answer.claims[0]
    evaluation = {
        "claim_id": claim.claim_id,
        "verdict": "SUPPORTED",
        "severity": "LOW",
        "reason_code": "DIRECT_EVIDENCE_SUPPORT",
        "evidence_ids": list(claim.evidence_ids),
    }
    if change == "unknown-claim":
        evaluation["claim_id"] = "unknown"
    elif change == "unknown-evidence":
        evaluation["evidence_ids"] = ["unknown"]
    elif change == "extra-reasoning":
        evaluation["reasoning"] = "private diagnostic"
    elif change == "bad-reason":
        evaluation["reason_code"] = "EVIDENCE_CONTRADICTION"
    rows = [evaluation, evaluation] if change == "duplicate" else [evaluation]
    with pytest.raises(SemanticEvaluationError, match="JUDGE_OUTPUT_INTEGRITY"):
        ClaimSupportJudge(FakeLLMClient([json.dumps({"evaluations": rows})])).evaluate(answer)


def test_judge_provider_failure_is_incomplete_without_fabricated_verdict(answer):
    client = FakeLLMClient([LLMProviderError("private provider diagnostic")])
    with pytest.raises(SemanticEvaluationError) as failure:
        ClaimSupportJudge(client).evaluate(answer)
    assert str(failure.value) == "JUDGE_PROVIDER_ERROR"
    assert client.call_count == 1
    assert len(failure.value.usage) == 1 and failure.value.usage[0].input_tokens is None


def test_judge_receives_only_relevant_transitive_provenance(answer):
    computation = answer.calculation_provenance[0]
    claim = answer.claims[0].model_copy(
        update={"claim_type": ClaimType.COMPUTED_FACT, "evidence_ids": (computation.evidence_id,)}
    )
    candidate = answer.model_copy(update={"claims": (claim,)})
    payload = json.loads(judge_payload(candidate))
    assert computation.evidence_id in payload["support_index"]
    for authority in payload["support_index"].values():
        if "calculation" in authority:
            assert (
                set(authority["calculation"]["input_evidence_ids"])
                <= payload["support_index"].keys()
            )
    assert len(payload["support_index"]) < len(answer.citations)


def test_sidecar_preserves_old_answer_and_grounding_integrity(answer):
    case = next(c for c in load_suite()[0].cases if c.case_id == "routing-fundamental_focus-en")
    fixture = load_fixtures(DEFAULT_ROOT)[case.fixture_scenario]
    result = (
        fixture_registry(fixture)
        .get(answer.used_skill_ids[0])
        .run(ticker=fixture.context.ticker, as_of_date=fixture.context.as_of_date)
    )
    projection = project_evidence(result)
    before = answer.model_dump_json()
    support = support_for_answer(answer, projection)
    validate_final_answer(answer, projection)
    assert answer.model_dump_json() == before
    assert support.claims[0].evidence_ids == answer.claims[0].evidence_ids
    assert "support_refs" not in answer.claims[0].model_dump()
    invalid = answer.model_copy(
        update={"claims": (answer.claims[0].model_copy(update={"evidence_ids": ("unknown",)}),)}
    )
    with pytest.raises(GroundingValidationError, match="UNKNOWN_CITATION"):
        validate_final_answer(invalid, projection)


def test_judge_rejects_sidecar_claim_changes_before_any_llm_call(answer):
    from financial_research.evals.judge import evidence_only_support

    original = evidence_only_support(answer)
    changed = original.model_copy(
        update={"claims": (original.claims[0].model_copy(update={"statement": "Changed claim."}),)}
    )
    client = FakeLLMClient([])
    with pytest.raises(SemanticEvaluationError, match="JUDGE_SUPPORT_MISMATCH"):
        ClaimSupportJudge(client).evaluate(answer, changed)
    assert client.call_count == 0
