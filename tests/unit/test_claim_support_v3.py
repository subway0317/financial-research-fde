import json

import pytest
from pydantic import ValidationError

from financial_research.agent.evidence_projection import project_evidence
from financial_research.evals.calibration import calibration_projection, load_calibration
from financial_research.evals.dataset import DEFAULT_ROOT
from financial_research.evals.fixtures import fixture_registry, load_fixtures
from financial_research.evals.judge import ClaimSupportJudge
from financial_research.evals.replay import load_replay_ledger
from financial_research.evals.support import (
    SUPPORT_PROJECTION_V2,
    AuthorityCategory,
    ClaimSupportProjection,
    StructuralSupport,
    SupportAuthority,
    SupportedClaim,
    SupportProjectionError,
    authority_catalog,
    project_claim_support,
    resolve_dependencies,
    support_id,
)
from financial_research.llm.fake import FakeLLMClient


@pytest.fixture
def project():
    fixture = load_fixtures(DEFAULT_ROOT)["warnings"]

    def build(skill):
        return project_evidence(
            fixture_registry(fixture)
            .get(skill)
            .run(ticker=fixture.context.ticker, as_of_date=fixture.context.as_of_date)
        )

    return build


def claim(statement, *, section="QUALITY", claim_type="SOURCE_FACT", refs=(), id="c1"):
    return SupportedClaim(
        claim_id=id,
        section=section,
        claim_type=claim_type,
        statement=statement,
        evidence_ids=refs,
    )


def own_authorities(support, id="c1"):
    scoped = next(c for c in support.claims if c.claim_id == id)
    return [support.support_index[k] for k in scoped.support_refs + scoped.dependency_refs]


@pytest.mark.parametrize("section", ["QUALITY", "MARKET"])
def test_market_window_collection_explicitly_distinguishes_absence_and_presence(project, section):
    for skill, state, count in [
        ("fundamental_analysis", "EMPTY", 0),
        ("equity_research", "NONEMPTY", 1),
    ]:
        projection = project(skill)
        support = project_claim_support(
            (claim("No market window is supplied.", section=section),), projection
        )
        states = [
            a.structural
            for a in own_authorities(support)
            if a.structural and a.structural.field == "market_windows"
        ]
        assert len(states) == 1
        assert states[0].state == state and states[0].count == count
        assert not any(a.evidence for a in own_authorities(support))


def test_structural_absence_is_closed_schema_and_only_copies_actual_fields(project):
    projection = project("fundamental_analysis")
    states = [a.structural for a in authority_catalog(projection).values() if a.structural]
    assert any(s.field == "company_name" and s.state == "MISSING" for s in states)
    assert any(
        s.field == "findings_by_section" and s.section == "MARKET" and s.state == "EMPTY"
        for s in states
    )
    for field in (
        "quality.selected_evidence_occurrences",
        "quality.first_affected_date",
        "quality.last_affected_date",
    ):
        assert {s.diagnostic_code for s in states if s.field == field} == {
            "CURRENT_COMPANY_REFERENCE",
            "MISSING_COMPANY_CURRENCY",
            "RETRIEVED_MARKET_VINTAGE",
        }
    with pytest.raises(ValidationError):
        StructuralSupport(field="all_uncited_financial_metrics", state="EMPTY", count=0)
    with pytest.raises(ValidationError, match="exact count"):
        StructuralSupport(field="market_windows", state="EMPTY", count=1)


@pytest.mark.parametrize(
    "wording", ["营业现金流", "经营现金流", "Cash conversion", "无关键词的表述"]
)
@pytest.mark.parametrize("claim_type", ["SOURCE_FACT", "COMPUTED_FACT", "INTERPRETATION"])
def test_quality_scope_is_structured_and_prose_independent(project, wording, claim_type):
    projection = project("equity_research")
    support = project_claim_support((claim(wording, claim_type=claim_type),), projection)
    baseline = project_claim_support(
        (claim("Unrelated wording", claim_type=claim_type),), projection
    )
    assert support.claims[0].support_refs == baseline.claims[0].support_refs
    authorities = own_authorities(support)
    assert {
        a.quality.diagnostic.code for a in authorities if a.quality and a.quality.diagnostic
    } == {
        "CURRENT_COMPANY_REFERENCE",
        "MISSING_COMPANY_CURRENCY",
        "RETRIEVED_MARKET_VINTAGE",
    }
    assert any(
        a.finding
        and a.finding.metric == "research_quality"
        and a.finding.status == "PASS_WITH_WARNINGS"
        for a in authorities
    )
    assert {
        a.finding.metric for a in authorities if a.finding and a.finding.status == "UNAVAILABLE"
    } == {
        "operating_cash_flow",
        "stockholders_equity",
    }
    assert {a.limitation.code for a in authorities if a.limitation} >= {
        "MISSING_METRIC:operating_cash_flow",
        "MISSING_METRIC:stockholders_equity",
        "MISSING_COMPANY_CURRENCY",
        "RETRIEVED_MARKET_VINTAGE",
    }
    assert not any(a.evidence or a.calculation for a in authorities)


def test_market_finding_state_has_exact_identity_and_excludes_fundamentals(project):
    projection = project("equity_research")
    # Deliberately different from its finding; scope must preserve the actual finding.
    projection = projection.model_copy(update={"skill_status": "SUCCESS"})
    support = project_claim_support((claim("市场表现综合发现", section="MARKET"),), projection)
    authorities = own_authorities(support)
    assert any(
        a.finding
        and a.finding.metric == "observed_market_behavior"
        and a.finding.status == "PARTIAL"
        for a in authorities
    )
    assert any(a.readiness and a.readiness.skill_status == "SUCCESS" for a in authorities)
    assert all(not a.finding or a.finding.section == "MARKET" for a in authorities)
    assert not any(a.evidence or a.quality for a in authorities)


def test_financial_comparator_not_autofilled_even_when_another_claim_cites_it(project):
    projection = project("fundamental_analysis")
    current = next(
        e
        for e in projection.evidence_index.values()
        if e.metric == "revenue" and str(e.value) == "150"
    )
    prior = next(
        e
        for e in projection.evidence_index.values()
        if e.metric == "revenue" and str(e.value) == "100"
    )
    claims = (
        claim(
            "Revenue is 150 USD for 2025-Q1 and 100 USD for 2024-Q1.",
            section="FUNDAMENTALS",
            refs=(current.evidence_id,),
        ),
        claim(
            "Revenue in the supplied prior quarter is 100 USD.",
            section="FUNDAMENTALS",
            refs=(prior.evidence_id,),
            id="c2",
        ),
    )
    support = project_claim_support(claims, projection)
    assert prior.evidence_id in support.support_index  # belongs only to c2
    assert all(
        not a.evidence or a.evidence.evidence_id == current.evidence_id
        for a in own_authorities(support)
    )
    assert support.claims[0].evidence_ids == (current.evidence_id,)
    assert (
        prior.evidence_id not in support.claims[0].support_refs + support.claims[0].dependency_refs
    )

    def judge_response(request):
        payload = json.loads(request.user_payload)
        assert payload["claims"][0]["evidence_ids"] == [current.evidence_id]
        assert prior.evidence_id not in payload["claims"][0]["support_refs"]
        return json.dumps(
            {
                "evaluations": [
                    {
                        "claim_id": c.claim_id,
                        "evidence_ids": c.evidence_ids,
                        "verdict": "INSUFFICIENT" if c.claim_id == "c1" else "SUPPORTED",
                        "severity": "MEDIUM" if c.claim_id == "c1" else "LOW",
                        "reason_code": "INSUFFICIENT_EVIDENCE"
                        if c.claim_id == "c1"
                        else "DIRECT_EVIDENCE_SUPPORT",
                    }
                    for c in claims
                ]
            }
        )

    result, _ = ClaimSupportJudge(FakeLLMClient([judge_response])).evaluate_projection(support)
    assert result[0].verdict == "INSUFFICIENT"  # scripted acceptance, not a real judgment


def test_nonfinancial_support_refs_cannot_smuggle_an_extra_financial_fact(project):
    projection = project("fundamental_analysis")
    sources = [
        e
        for e in projection.evidence_index.values()
        if e.metric == "revenue" and e.kind != "COMPUTATION"
    ]
    source, extra = sources[:2]
    supplied = claim("A compound financial claim", refs=(source.evidence_id,))
    with pytest.raises(SupportProjectionError, match="FINANCIAL_SUPPORT_OUTSIDE_CITATIONS"):
        project_claim_support(
            (supplied.model_copy(update={"support_refs": (extra.evidence_id,)}),), projection
        )
    support = project_claim_support((supplied,), projection)
    data = support.model_dump()
    data["support_index"][extra.evidence_id] = SupportAuthority(
        category=AuthorityCategory.SOURCE_EVIDENCE, evidence=extra
    ).model_dump()
    data["claims"][0]["support_refs"] += (extra.evidence_id,)
    with pytest.raises(ValidationError, match="only from explicit"):
        ClaimSupportProjection.model_validate(data)


def test_financial_closure_still_includes_only_explicit_calculation_inputs(project):
    projection = project("fundamental_analysis")
    calc = next(c for c in projection.calculation_provenance if c.formula == "current - prior")
    support = project_claim_support(
        (
            claim(
                "Computed fact",
                section="FUNDAMENTALS",
                claim_type="COMPUTED_FACT",
                refs=(calc.evidence_id,),
            ),
        ),
        projection,
    )
    expected = resolve_dependencies({calc.evidence_id}, authority_catalog(projection))
    assert {k for k, a in support.support_index.items() if a.evidence} == expected


def test_v2_content_addresses_and_serialized_projection_remain_readable(project):
    authority = next(a for a in authority_catalog(project("equity_research")).values() if a.quality)
    key = support_id(authority, SUPPORT_PROJECTION_V2)
    archived = ClaimSupportProjection(
        support_projection_version=SUPPORT_PROJECTION_V2,
        claims=(claim("Recorded quality state").model_copy(update={"support_refs": (key,)}),),
        support_index={key: authority},
    )
    assert ClaimSupportProjection.model_validate_json(archived.model_dump_json()) == archived
    assert key != support_id(authority)


def test_calibration_v2_retains_original_cases_and_independent_new_coverage(project):
    v1 = load_calibration(version="stage5-judge-calibration-v1")
    v2 = load_calibration()
    assert v2.cases[:16] == v1.cases
    assert len(v2.cases) == 26
    for case in v2.cases[16:]:
        support = calibration_projection(case, project(case.skill_id))
        financial = {k for k, a in support.support_index.items() if a.evidence}
        assert financial == set(case.claim.evidence_ids)
        if case.expected_verdict == "INSUFFICIENT":
            assert "comparator" in case.case_id
            assert len(financial) == 1


def test_replay_ledger_covers_exact_identified_defects_and_citation_omissions():
    ledger = load_replay_ledger()
    assert {
        kind: sum(t.kind == kind for t in ledger.targets)
        for kind in ["BINDING", "ABSENCE", "FINANCIAL_CITATION"]
    } == {
        "BINDING": 10,
        "ABSENCE": 5,
        "FINANCIAL_CITATION": 5,
    }
    assert {t.audit_number for t in ledger.targets if t.kind == "FINANCIAL_CITATION"} == {
        5,
        6,
        14,
        18,
        20,
    }
