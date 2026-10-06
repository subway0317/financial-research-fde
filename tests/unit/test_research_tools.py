import math
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from financial_research.exceptions import DataValidationError, UnsupportedMetricError
from financial_research.schemas.quality import QualityIssue, QualityReport, QualityStatus, Severity
from financial_research.schemas.tools import EvidenceKind, PercentageChangeStatus, ResultStatus
from financial_research.tools import (
    ResearchTools,
    analyze_fundamental_trends,
    compare_periods,
    get_company_snapshot,
    inspect_research_quality,
    summarize_market_behavior,
)


def assert_grounding(result) -> None:
    by_id = {e.evidence_id: e for e in result.evidence}
    for calculation in result.calculation_provenance:
        assert by_id[calculation.evidence_id].kind == EvidenceKind.COMPUTATION
        assert calculation.input_evidence_ids
        assert set(calculation.input_evidence_ids) <= by_id.keys()
        assert all(
            by_id[e].kind == EvidenceKind.SOURCE_FACT for e in calculation.input_evidence_ids
        )


def test_trends_valid_pairs_and_financial_percentage_semantics(fiscal_context) -> None:
    result = analyze_fundamental_trends(fiscal_context)
    rows = {row.metric: row for row in result.metrics}
    assert rows["revenue"].absolute_change == 50
    assert rows["revenue"].percentage_change == Decimal("0.5")
    assert rows["revenue"].direction == "INCREASED"
    assert rows["gross_profit"].absolute_change == 100
    assert rows["gross_profit"].comparable_observation.fiscal_period.frequency == "ANNUAL"
    assert rows["net_income"].absolute_change == 250
    assert rows["net_income"].percentage_change is None
    assert rows["net_income"].percentage_change_status == PercentageChangeStatus.NOT_MEANINGFUL
    assert rows["operating_income"].absolute_change == 10
    assert rows["operating_income"].percentage_change is None
    assert rows["cash_and_equivalents"].direction == "DECREASED"
    assert rows["total_assets"].direction == "UNCHANGED"
    assert rows["operating_cash_flow"].comparison_status == ResultStatus.UNAVAILABLE
    assert rows["operating_cash_flow"].limitations == ("NO_CURRENT_OBSERVATION",)
    assert_grounding(result)


def test_primitive_and_composite_comparison_match(fiscal_context) -> None:
    primitive = compare_periods(fiscal_context, metric="revenue")
    composite = analyze_fundamental_trends(fiscal_context, metrics=["revenue"])
    assert primitive.result == composite.metrics[0]
    assert primitive.result.comparison_type == "YEAR_OVER_YEAR"
    assert_grounding(primitive)


def test_missing_comparable_is_structured_unavailable(fiscal_context) -> None:
    observations = tuple(
        o
        for o in fiscal_context.fundamentals.observations
        if o.metric != "revenue" or o.period_end.year == 2025
    )
    context = fiscal_context.model_copy(
        update={
            "fundamentals": fiscal_context.fundamentals.model_copy(
                update={"observations": observations}
            )
        }
    )
    result = compare_periods(context, metric="revenue").result
    assert result.comparison_status == ResultStatus.UNAVAILABLE
    assert result.absolute_change is None
    assert result.direction == "UNAVAILABLE"
    assert result.limitations == ("NO_COMPARABLE_PRIOR_PERIOD",)


def test_unsupported_differs_from_missing(fiscal_context) -> None:
    with pytest.raises(UnsupportedMetricError):
        analyze_fundamental_trends(fiscal_context, metrics=["EBITDA"])
    missing = analyze_fundamental_trends(fiscal_context, metrics=["stockholders_equity"])
    assert missing.metrics[0].comparison_status == ResultStatus.UNAVAILABLE


def test_observed_session_market_window_and_nonannualized_volatility(nvda_context) -> None:
    result = summarize_market_behavior(nvda_context, lookback_sessions=6)
    bars = nvda_context.market.observations[-6:]
    assert result.window.lookback_sessions_available == 6
    assert (bars[-1].date - bars[0].date).days > 4  # A weekend separates observed sessions.
    assert result.window.cumulative_return == pytest.approx(bars[-1].close / bars[0].close - 1)
    assert result.window.realized_volatility_daily == pytest.approx(math.sqrt(0.00027))
    assert result.window.annualized is False
    assert result.window.window_high == max(bar.high for bar in bars)
    assert result.window.window_low == min(bar.low for bar in bars)
    assert (
        result.latest_market_features.close_to_sma_60
        == nvda_context.market.features[-1].close_to_sma_60
    )
    assert_grounding(result)


def test_two_closes_have_return_but_no_sample_volatility(nvda_context) -> None:
    result = summarize_market_behavior(nvda_context, lookback_sessions=2)
    assert result.window.status == ResultStatus.AVAILABLE
    assert result.window.cumulative_return is not None
    assert result.window.realized_volatility_daily is None
    assert result.window.volatility_status == ResultStatus.UNAVAILABLE


@pytest.mark.parametrize("lookback", [0, 1, 505, -1, True, 2.5, "60"])
def test_bad_lookback_is_explicit(nvda_context, lookback) -> None:
    with pytest.raises(DataValidationError):
        summarize_market_behavior(nvda_context, lookback_sessions=lookback)


def test_insufficient_history_does_not_use_partial_window(nvda_context) -> None:
    result = summarize_market_behavior(nvda_context, lookback_sessions=100)
    assert result.window.status == ResultStatus.UNAVAILABLE
    assert result.window.lookback_sessions_available == 70
    assert result.window.cumulative_return is None
    assert result.window.realized_volatility_daily is None


def test_company_snapshot_latest_state_and_standard_windows(fiscal_context) -> None:
    result = get_company_snapshot(fiscal_context)
    assert result.latest_market_session == date(2025, 5, 23)
    assert [w.lookback_sessions_requested for w in result.market_windows] == [5, 20, 60]
    revenue = next(f for f in result.fundamentals if f.metric == "revenue")
    assert revenue.observation.value == 150
    assert result.quality == fiscal_context.quality
    assert_grounding(result)


def test_quality_preserves_stage1_rules_and_objective_age(fiscal_context) -> None:
    result = inspect_research_quality(fiscal_context)
    assert result.overall_status == fiscal_context.quality.status
    assert result.issues == fiscal_context.quality.issues
    assert result.market_age_calendar_days == 2
    assert result.fundamental_age_calendar_days == 2
    assert "operating_cash_flow" in result.missing_registered_metrics
    assert "revenue" in result.available_registered_metrics
    assert result.provenance_summary == fiscal_context.provenance
    assert_grounding(result)


def test_quality_fail_is_propagated_and_blocks_calculations(fiscal_context) -> None:
    report = QualityReport.from_issues(
        (
            *fiscal_context.quality.issues,
            QualityIssue(
                code="CONFLICT", severity=Severity.ERROR, message="conflicting source facts"
            ),
        )
    )
    context = fiscal_context.model_copy(update={"quality": report})
    assert inspect_research_quality(context).overall_status == QualityStatus.FAIL
    with pytest.raises(DataValidationError):
        get_company_snapshot(context)


def test_fixed_context_results_and_evidence_ids_are_deterministic(fiscal_context) -> None:
    first = get_company_snapshot(fiscal_context)
    observations = tuple(
        o.model_copy(update={"retrieved_at": datetime(2040, 1, 1, tzinfo=UTC)})
        for o in fiscal_context.fundamentals.observations
    )
    later = fiscal_context.model_copy(
        update={
            "fundamentals": fiscal_context.fundamentals.model_copy(
                update={"observations": observations}
            ),
            "generated_at": datetime(2040, 1, 1, tzinfo=UTC),
        }
    )
    second = get_company_snapshot(later)
    assert first.normalized_business_json() == second.normalized_business_json()


def test_facade_rejects_unsupported_before_provider_io() -> None:
    class NeverBuild:
        def build(self, **kwargs):
            raise AssertionError("unsupported request must not download data")

    with pytest.raises(UnsupportedMetricError):
        ResearchTools(NeverBuild()).compare_periods(
            ticker="NVDA", as_of_date=date(2025, 5, 25), metric="EBITDA"
        )
