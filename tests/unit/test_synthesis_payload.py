import json
import logging
from collections import Counter
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from financial_research.agent.evidence_projection import project_evidence
from financial_research.agent.grounding import validate_grounding
from financial_research.agent.service import ResearchAgent
from financial_research.agent.synthesis_payload import synthesis_payload, synthesis_projection
from financial_research.llm.fake import FakeLLMClient
from financial_research.schemas.agent import ResearchAgentRequest, SynthesisOutput
from financial_research.schemas.quality import QualityIssue, QualityReport, Severity
from financial_research.skills.defaults import create_skill_registry

QUESTION = "How have NVDA's fundamentals changed?"


@pytest.fixture
def fundamental_result(fiscal_context):
    class Builder:
        def build(self, *, ticker, as_of_date):
            return fiscal_context

    return (
        create_skill_registry(Builder())
        .get("fundamental_analysis")
        .run(ticker="NVDA", as_of_date=date(2025, 5, 25))
    )


@pytest.fixture
def history_projection(fundamental_result):
    projection = project_evidence(fundamental_result)
    history = tuple(
        QualityIssue(
            code="HISTORICAL_OUT_OF_SCOPE",
            severity=Severity.INFO,
            message="filing predates requested history; availability not fabricated",
            affected_field=("revenue", "net_income", "total_assets")[i % 3],
            affected_date=date(2010, 1, 1) + timedelta(days=i % 3000),
            affected_context=f"offline-accession-{i:06d}",
        )
        for i in range(2000)
    )
    return projection.model_copy(
        update={"quality": QualityReport.from_issues((*projection.quality.issues, *history))}
    )


def test_compact_payload_is_bounded_and_avoids_full_packages_and_provider_data(history_projection):
    payload, audit = synthesis_payload(question=QUESTION, projection=history_projection)
    data = json.loads(payload)["projection"]
    assert len(payload.encode("utf-8")) == audit.request_bytes
    assert audit.request_bytes < 32_000
    assert audit.request_bytes < audit.baseline_request_bytes * 0.1
    assert audit.components.quality_bytes < audit.baseline_quality_bytes * 0.01
    assert audit.quality_issue_count == 2003
    assert audit.quality_group_count == 6
    assert set(data) <= {
        "projection_version",
        "ticker",
        "as_of_date",
        "skill_id",
        "skill_status",
        "synthesis_readiness",
        "quality",
        "company_name",
        "market_windows",
        "findings",
        "evidence_index",
        "calculation_provenance",
        "limitations",
    }
    assert data["skill_id"] == "fundamental_analysis"
    for forbidden in (
        "metadata",
        "execution_trace",
        "subskill_metadata",
        "fundamental_analysis",
        "current_observation",
        "comparable_observation",
        "companyfacts",
        "chart",
    ):
        # Source URLs may legitimately include companyfacts, but no raw payload keys exist.
        assert f'"{forbidden}":' not in payload


def test_definitions_are_singletons_and_all_provenance_references_resolve(history_projection):
    payload, _ = synthesis_payload(question=QUESTION, projection=history_projection)
    data = json.loads(payload)["projection"]
    assert set(data["evidence_index"]) == set(history_projection.evidence_index)
    source_definitions = 0
    for key, definition in data["evidence_index"].items():
        assert "evidence_id" not in definition
        source_definitions += 1
        original = history_projection.evidence_index[key].model_dump(
            mode="json", exclude={"evidence_id"}, exclude_none=True
        )
        assert definition == original
    assert source_definitions == len(history_projection.evidence_index)
    original_calcs = {calc.evidence_id: calc for calc in history_projection.calculation_provenance}
    assert set(data["calculation_provenance"]) == set(original_calcs)
    for key, calculation in data["calculation_provenance"].items():
        assert key in data["evidence_index"]
        assert "evidence_id" not in calculation
        assert all(isinstance(input_id, str) for input_id in calculation["input_evidence_ids"])
        assert set(calculation["input_evidence_ids"]) <= data["evidence_index"].keys()
        assert calculation == original_calcs[key].model_dump(mode="json", exclude={"evidence_id"})
    for finding in data["findings"]:
        assert "calculation_ids" not in finding
        assert set(finding["evidence_ids"]) <= data["evidence_index"].keys()


def test_quality_templates_counts_warnings_and_limitations_are_preserved(history_projection):
    compact = synthesis_projection(history_projection)
    originals = Counter(
        (issue.severity, issue.code, issue.message, issue.affected_field)
        for issue in history_projection.quality.issues
    )
    summary = {
        (group.severity, group.code, group.message, group.affected_field): group.count
        for group in compact.quality.groups
    }
    assert summary == originals
    assert compact.quality.status == history_projection.quality.status
    assert compact.quality.issue_count == len(history_projection.quality.issues)
    assert compact.limitations == history_projection.limitations
    historical = [
        group for group in compact.quality.groups if group.code == "HISTORICAL_OUT_OF_SCOPE"
    ]
    assert all(
        group.first_affected_date is not None and group.last_affected_date is not None
        for group in historical
    )
    assert not any(group.selected_evidence_occurrences for group in historical)


def test_matching_selected_warning_keeps_exact_context_and_date(history_projection):
    reference = next(
        ref for ref in history_projection.evidence_index.values() if ref.kind == "SOURCE_FACT"
    )
    accession = reference.source_reference.rsplit("/", 1)[-1]
    issue = QualityIssue(
        code="ALIAS_VALUE_CONFLICT",
        severity=Severity.WARNING,
        message="Selected alias has a source conflict.",
        affected_field=reference.metric,
        affected_date=reference.period_end,
        affected_context=accession,
    )
    projection = history_projection.model_copy(
        update={
            "quality": QualityReport.from_issues((*history_projection.quality.issues, issue, issue))
        }
    )
    group = next(
        group
        for group in synthesis_projection(projection).quality.groups
        if group.code == "ALIAS_VALUE_CONFLICT"
    )
    assert group.count == 2
    assert len(group.selected_evidence_occurrences) == 1
    occurrence = group.selected_evidence_occurrences[0]
    assert occurrence.affected_context == accession
    assert occurrence.affected_date == reference.period_end
    assert occurrence.count == 2


def test_payload_is_deterministic_without_mutating_canonical_projection(history_projection):
    before = history_projection.model_dump_json()
    reordered = history_projection.model_copy(
        update={
            "evidence_index": dict(reversed(list(history_projection.evidence_index.items()))),
            "calculation_provenance": tuple(reversed(history_projection.calculation_provenance)),
            "findings": tuple(reversed(history_projection.findings)),
            "quality": history_projection.quality.model_copy(
                update={"issues": tuple(reversed(history_projection.quality.issues))}
            ),
        }
    )
    first, _ = synthesis_payload(question=QUESTION, projection=history_projection)
    second, _ = synthesis_payload(question=QUESTION, projection=reordered)
    assert first == second
    assert history_projection.model_dump_json() == before


def test_every_wire_evidence_id_is_citable_with_original_grounder(history_projection):
    payload, _ = synthesis_payload(question=QUESTION, projection=history_projection)
    data = json.loads(payload)["projection"]
    for key, definition in data["evidence_index"].items():
        output = SynthesisOutput.model_validate(
            {
                "used_skill_ids": [data["skill_id"]],
                "claims": [
                    {
                        "claim_id": "c1",
                        "section": "FUNDAMENTALS",
                        "claim_type": "SOURCE_FACT"
                        if definition["kind"] == "SOURCE_FACT"
                        else "COMPUTED_FACT",
                        "statement": "Supplied evidence is available.",
                        "evidence_ids": [key],
                    }
                ],
            }
        )
        validate_grounding(output, history_projection)


def test_compact_projection_rejects_unresolved_calculation_input(history_projection):
    compact = synthesis_projection(history_projection)
    key, calc = next(iter(compact.calculation_provenance.items()))
    with pytest.raises(ValidationError, match="calculation references"):
        type(compact).model_validate(
            {
                **compact.model_dump(),
                "evidence_index": compact.evidence_index,
                "calculation_provenance": {
                    **compact.calculation_provenance,
                    key: calc.model_copy(update={"input_evidence_ids": ("unknown",)}),
                },
            }
        )


def test_actual_service_sends_compact_payload_and_retains_canonical_answer(
    fiscal_context, history_projection, caplog
):
    from financial_research.schemas.skills import FundamentalAnalysisResult

    class Builder:
        def build(self, **kwargs):
            return fiscal_context

    registered = create_skill_registry(Builder())
    original = registered.get("fundamental_analysis")
    result = original.run(ticker="NVDA", as_of_date=date(2025, 5, 25))
    result = FundamentalAnalysisResult.model_validate(
        {
            **result.model_dump(),
            "metadata": {**result.metadata.model_dump(), "quality": history_projection.quality},
        }
    )

    class FixedSkill:
        definition = original.definition

        def run(self, **kwargs):
            return result

        def run_from_context(self, execution):
            return result

    from financial_research.skills.registry import SkillRegistry

    registry = SkillRegistry()
    registry.register(FixedSkill())

    def synthesize(request):
        data = json.loads(request.user_payload)["projection"]
        assert "groups" in data["quality"] and "issues" not in data["quality"]
        return json.dumps(
            {
                "used_skill_ids": [data["skill_id"]],
                "claims": [
                    {
                        "claim_id": "c1",
                        "section": "FUNDAMENTALS",
                        "claim_type": "INTERPRETATION",
                        "statement": "Supplied fundamental evidence is available.",
                        "evidence_ids": [next(iter(data["evidence_index"]))],
                    }
                ],
            }
        )

    plan = {
        "plan_version": "1.0",
        "intent": "FUNDAMENTAL_FOCUS",
        "selected_skill_id": "fundamental_analysis",
        "reason_code": "FUNDAMENTAL_ANALYSIS_REQUEST",
        "ticker": "NVDA",
        "as_of_date": "2025-05-25",
        "requested_focus": None,
    }
    client = FakeLLMClient([json.dumps(plan), synthesize])
    caplog.set_level(logging.INFO)
    answer = ResearchAgent(registry=registry, llm=client).run(
        ResearchAgentRequest(
            question="private-question-text", ticker="NVDA", as_of_date=date(2025, 5, 25)
        )
    )
    assert client.call_count == 2
    assert answer.agent_status == "COMPLETED_WITH_WARNINGS"
    assert answer.synthesis_readiness == "READY_WITH_WARNINGS"
    assert answer.quality == result.metadata.quality
    assert answer.limitations == result.limitations
    assert answer.citations == result.evidence_index
    assert answer.calculation_provenance == result.calculation_provenance
    assert answer.synthesis_payload_audit.request_bytes < 32_000
    assert answer.synthesis_prompt_version == "stage5-synthesis-v1"
    assert "private-question-text" not in caplog.text
    assert "offline-accession-" not in answer.synthesis_payload_audit.model_dump_json()
