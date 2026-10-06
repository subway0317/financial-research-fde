import json

import pytest
from pydantic import ValidationError

from financial_research.agent.evidence_projection import project_evidence
from financial_research.evals.dataset import DEFAULT_ROOT
from financial_research.evals.fixtures import fixture_registry, load_fixtures
from financial_research.evals.support import (
    ClaimSupportProjection,
    SupportedClaim,
    SupportProjectionError,
    authority_catalog,
    project_claim_support,
    support_id,
)


@pytest.fixture
def projection():
    fixture = load_fixtures(DEFAULT_ROOT)["warnings"]
    result = (
        fixture_registry(fixture)
        .get("equity_research")
        .run(ticker=fixture.context.ticker, as_of_date=fixture.context.as_of_date)
    )
    return project_evidence(result)


def claim(text, evidence_ids=(), support_refs=(), claim_type="SOURCE_FACT", section="QUALITY"):
    return SupportedClaim(
        claim_id="c1",
        section=section,
        claim_type=claim_type,
        statement=text,
        evidence_ids=evidence_ids,
        support_refs=support_refs,
    )


def categories(support):
    return {value.category for value in support.support_index.values()}


@pytest.mark.parametrize(
    "text,category",
    [
        ("CURRENT_COMPANY_REFERENCE is a WARNING diagnostic with count 1.", "QUALITY_DIAGNOSTIC"),
        ("技能执行状态为 PARTIAL，综合准备状态为 READY_WITH_WARNINGS。", "READINESS_STATE"),
        ("NVDA is the supplied ticker as of 2025-05-25.", "COMPANY_CONTEXT"),
        (
            "经营现金流百分比变化状态为 UNAVAILABLE，限制为 NO_CURRENT_OBSERVATION。",
            "COMPARISON_STATE",
        ),
        ("经营现金流限制为 NO_CURRENT_OBSERVATION。", "LIMITATION"),
    ],
)
def test_nonfinancial_claim_receives_typed_support_without_fake_financial_anchor(
    projection, text, category
):
    support = project_claim_support((claim(text),), projection)
    assert category in categories(support)
    assert support.claims[0].evidence_ids == ()
    assert not {"SOURCE_EVIDENCE", "CALCULATION"} & categories(support)
    assert support.claims[0].support_refs


def test_availability_has_its_own_authority_for_company_snapshot():
    fixture = load_fixtures(DEFAULT_ROOT)["warnings"]
    result = (
        fixture_registry(fixture)
        .get("company_overview")
        .run(ticker=fixture.context.ticker, as_of_date=fixture.context.as_of_date)
    )
    support = project_claim_support(
        (claim("经营现金流的状态为 UNAVAILABLE。"),), project_evidence(result)
    )
    assert "AVAILABILITY_STATE" in categories(support)
    assert any(
        a.finding
        and a.finding.metric == "operating_cash_flow"
        and a.finding.status == "UNAVAILABLE"
        for a in support.support_index.values()
    )
    assert not any(a.evidence for a in support.support_index.values())


def test_financial_ids_and_source_metadata_are_preserved_and_unrelated_history_excluded(projection):
    reference = next(
        ref
        for ref in projection.evidence_index.values()
        if ref.metric == "revenue" and str(ref.value) == "150"
    )
    support = project_claim_support(
        (
            claim(
                "Revenue for 2025-01-01 through 2025-03-31 is 150 USD.",
                (reference.evidence_id,),
                section="FUNDAMENTALS",
            ),
        ),
        projection,
    )
    assert {key for key, a in support.support_index.items() if a.evidence} == {
        reference.evidence_id
    }
    assert support.support_index[reference.evidence_id].evidence == reference
    assert support.claims[0].evidence_ids == (reference.evidence_id,)


def test_computation_chain_and_comparison_state_are_both_supplied(projection):
    calculation = next(
        c
        for c in projection.calculation_provenance
        if projection.evidence_index[c.evidence_id].metric == "revenue"
        and c.formula == "current - prior"
    )
    support = project_claim_support(
        (
            claim(
                "Revenue increased 50 USD; percentage-change status is MEANINGFUL.",
                (calculation.evidence_id,),
                claim_type="COMPUTED_FACT",
                section="FUNDAMENTALS",
            ),
        ),
        projection,
    )
    assert {"CALCULATION", "SOURCE_EVIDENCE", "COMPARISON_STATE"} <= categories(support)
    assert set(calculation.input_evidence_ids) == set(support.claims[0].dependency_refs)
    assert support.support_index[calculation.evidence_id].calculation == calculation
    assert any(
        a.finding
        and a.finding.metric == "revenue"
        and a.finding.percentage_change_status == "MEANINGFUL"
        for a in support.support_index.values()
    )
    assert all(
        not a.finding or a.finding.section in {"FUNDAMENTALS", "QUALITY"}
        for a in support.support_index.values()
    )


def test_window_state_is_scoped_to_cited_calculation(projection):
    calculation = next(
        c
        for c in projection.calculation_provenance
        if projection.evidence_index[c.evidence_id].metric == "realized_volatility_daily"
    )
    support = project_claim_support(
        (
            claim(
                "60-session window volatility status is AVAILABLE.",
                (calculation.evidence_id,),
                claim_type="COMPUTED_FACT",
                section="MARKET",
            ),
        ),
        projection,
    )
    assert "MARKET_WINDOW_STATE" in categories(support)
    assert len(support.claims[0].dependency_refs) == 60
    assert "QUALITY_DIAGNOSTIC" not in categories(support)
    compact = json.loads(support.payload())
    transmitted = compact["claims"][0]
    assert "dependency_refs" not in transmitted
    assert not set(transmitted["evidence_ids"]) & set(transmitted["support_refs"])
    # Every omitted duplicate dependency is still carried by the explicit calculation edges.
    assert set(support.claims[0].dependency_refs) <= compact["support_index"].keys()


def test_unknown_explicit_support_reference_fails(projection):
    with pytest.raises(SupportProjectionError, match="UNKNOWN_SUPPORT_REF"):
        project_claim_support(
            (claim("A warning exists.", support_refs=("quality:missing",)),), projection
        )


def test_support_ids_deterministic_resolvable_and_content_checked(projection):
    first = project_claim_support((claim("CURRENT_COMPANY_REFERENCE is WARNING."),), projection)
    assert first == project_claim_support(
        (claim("CURRENT_COMPANY_REFERENCE is WARNING."),), projection
    )
    assert all(
        key == support_id(authority) for key, authority in authority_catalog(projection).items()
    )
    for c in first.claims:
        assert set(c.support_refs + c.dependency_refs) <= first.support_index.keys()
    wrong = first.model_dump()
    key = next(iter(wrong["support_index"]))
    wrong["support_index"]["quality:incorrect"] = wrong["support_index"].pop(key)
    with pytest.raises(ValidationError, match="support ID"):
        ClaimSupportProjection.model_validate(wrong)


def test_unknown_ref_and_mutable_index_cannot_reach_judge(projection):
    support = project_claim_support((claim("CURRENT_COMPANY_REFERENCE is WARNING."),), projection)
    support.support_index.clear()
    with pytest.raises(ValidationError, match="UNKNOWN_SUPPORT_REF"):
        support.payload()


def test_quality_scope_includes_all_supplied_diagnostics_without_financial_facts(projection):
    support = project_claim_support((claim("CURRENT_COMPANY_REFERENCE has count 1."),), projection)
    groups = [
        a.quality.diagnostic.code
        for a in support.support_index.values()
        if a.quality and a.quality.diagnostic
    ]
    assert set(groups) == {
        "CURRENT_COMPANY_REFERENCE",
        "MISSING_COMPANY_CURRENCY",
        "RETRIEVED_MARKET_VINTAGE",
    }
    assert not any(a.evidence for a in support.support_index.values())
    assert any(
        a.finding and a.finding.metric == "research_quality" for a in support.support_index.values()
    )
    payload = json.loads(support.payload())
    assert "question" not in payload and "projection" not in payload
