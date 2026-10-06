from datetime import date

import pytest

from financial_research.exceptions import ProviderError
from financial_research.schemas.quality import QualityIssue, QualityReport, Severity
from financial_research.schemas.skills import SkillStatus, TraceAction
from financial_research.skills.company_overview import CompanyOverviewSkill
from financial_research.skills.context import SkillExecutionContext
from financial_research.skills.fundamental_analysis import FundamentalAnalysisSkill
from financial_research.skills.market_analysis import MarketAnalysisSkill
from financial_research.skills.research_quality import ResearchQualityAuditSkill
from financial_research.tools import analyze_fundamental_trends, summarize_market_behavior


def execution(context):
    return SkillExecutionContext(
        ticker=context.ticker,
        as_of_date=context.as_of_date,
        research_context=context,
    )


def test_company_overview_composes_snapshot_and_preserves_missing_support(fiscal_context) -> None:
    result = CompanyOverviewSkill().run_from_context(execution(fiscal_context))
    assert result.metadata.status == SkillStatus.PARTIAL
    assert result.company_overview.company == fiscal_context.company
    assert result.company_overview.latest_close == fiscal_context.market.observations[-1].close
    assert len(result.company_overview.market_windows) == 3
    assert result.metadata.quality == fiscal_context.quality
    assert "NO_CURRENT_OBSERVATION" in result.limitations
    assert set(result.company_overview.evidence_ids) == result.evidence_index.keys()


def test_fundamental_skill_preserves_tool_values_and_provenance(fiscal_context) -> None:
    names = ["revenue", "net_income"]
    tool = analyze_fundamental_trends(fiscal_context, metrics=names)
    result = FundamentalAnalysisSkill().run_from_context(execution(fiscal_context), metrics=names)
    assert result.metadata.status == SkillStatus.SUCCESS
    assert result.metadata.quality.status == "PASS_WITH_WARNINGS"
    assert result.fundamental_analysis.available_metrics == tuple(names)
    assert result.fundamental_analysis.unavailable_metrics == ()
    for section_row, tool_row in zip(
        result.fundamental_analysis.metrics, tool.metrics, strict=True
    ):
        assert section_row.absolute_change == tool_row.absolute_change
        assert section_row.percentage_change == tool_row.percentage_change
        assert section_row.direction == tool_row.direction
        assert set(section_row.evidence_ids) == {ref.evidence_id for ref in tool_row.evidence}
        assert not hasattr(section_row, "evidence")
    assert {calc.evidence_id: calc for calc in result.calculation_provenance} == {
        calc.evidence_id: calc for calc in tool.calculation_provenance
    }


def test_fundamental_partial_and_unavailable_are_data_states(fiscal_context) -> None:
    skill = FundamentalAnalysisSkill()
    partial = skill.run_from_context(
        execution(fiscal_context), metrics=["revenue", "stockholders_equity"]
    )
    assert partial.metadata.status == SkillStatus.PARTIAL
    assert partial.fundamental_analysis.unavailable_metrics == ("stockholders_equity",)
    unavailable = skill.run_from_context(execution(fiscal_context), metrics=["stockholders_equity"])
    assert unavailable.metadata.status == SkillStatus.UNAVAILABLE
    assert unavailable.metadata.error is None


def test_market_skill_composes_and_distinguishes_optional_volatility(nvda_context) -> None:
    skill = MarketAnalysisSkill()
    normal = skill.run_from_context(execution(nvda_context))
    assert normal.metadata.status == SkillStatus.SUCCESS
    assert normal.market_analysis.window == summarize_market_behavior(nvda_context).window
    assert normal.market_analysis.descriptive_only is True
    partial = skill.run_from_context(execution(nvda_context), lookback_sessions=2)
    assert partial.metadata.status == SkillStatus.PARTIAL
    assert partial.market_analysis.window.cumulative_return is not None
    missing = skill.run_from_context(execution(nvda_context), lookback_sessions=100)
    assert missing.metadata.status == SkillStatus.UNAVAILABLE
    assert missing.market_analysis.window.cumulative_return is None


def test_market_reuses_snapshot_window_without_calculating_again(
    fiscal_context, monkeypatch
) -> None:
    shared = execution(fiscal_context)
    CompanyOverviewSkill().run_from_context(shared)

    def forbidden(*args, **kwargs):
        raise AssertionError("snapshot already contains the requested market window")

    monkeypatch.setattr("financial_research.skills.context.summarize_market_behavior", forbidden)
    result = MarketAnalysisSkill().run_from_context(shared)
    assert result.metadata.status == SkillStatus.SUCCESS
    expected = summarize_market_behavior(fiscal_context)
    assert result.market_analysis.window == expected.window
    assert {c.evidence_id: c for c in result.calculation_provenance} == {
        c.evidence_id: c for c in expected.calculation_provenance
    }
    assert set(result.evidence_index) == {ref.evidence_id for ref in expected.evidence}
    assert any(step.action_type == TraceAction.TOOL_REUSE for step in result.execution_trace.steps)


def test_quality_audit_retains_authoritative_issues_and_failed_diagnostics(fiscal_context) -> None:
    skill = ResearchQualityAuditSkill()
    normal = skill.run_from_context(execution(fiscal_context))
    assert normal.metadata.status == SkillStatus.SUCCESS
    assert normal.research_quality.issues == fiscal_context.quality.issues
    assert normal.research_quality.fundamental_age_calendar_days == 2
    report = QualityReport.from_issues(
        (
            *fiscal_context.quality.issues,
            QualityIssue(
                code="CONFLICT", severity=Severity.ERROR, message="Conflicting source facts."
            ),
        )
    )
    context = fiscal_context.model_copy(update={"quality": report})
    failed = skill.run_from_context(execution(context))
    assert failed.metadata.status == SkillStatus.FAILED
    assert failed.metadata.error.error_code == "CRITICAL_QUALITY_FAILURE"
    assert failed.research_quality.critical_issues[-1].code == "CONFLICT"
    assert failed.research_quality.overall_status == "FAIL"


def test_custom_market_window_reuses_relative_sma_calculations(fiscal_context, monkeypatch) -> None:
    shared = execution(fiscal_context)
    CompanyOverviewSkill().run_from_context(shared)

    def forbidden(*args, **kwargs):
        raise AssertionError("relative SMA has already been computed")

    monkeypatch.setattr("financial_research.skills.context.summarize_market_behavior", forbidden)
    result = MarketAnalysisSkill().run_from_context(shared, lookback_sessions=10)
    expected = summarize_market_behavior(fiscal_context, lookback_sessions=10)
    assert result.metadata.status == SkillStatus.SUCCESS
    assert result.market_analysis.window == expected.window
    assert {c.evidence_id: c for c in result.calculation_provenance} == {
        c.evidence_id: c for c in expected.calculation_provenance
    }


@pytest.mark.parametrize(
    "skill_type",
    [
        CompanyOverviewSkill,
        FundamentalAnalysisSkill,
        MarketAnalysisSkill,
        ResearchQualityAuditSkill,
    ],
)
def test_provider_failures_are_failed_with_sanitized_metadata(skill_type) -> None:
    class Broken:
        def build(self, **kwargs):
            raise ProviderError("secret-token raw-provider-payload /private/path")

    result = skill_type(Broken()).run(ticker="NVDA", as_of_date=date(2026, 6, 30))
    assert result.metadata.status == SkillStatus.FAILED
    assert result.metadata.error.error_code == "PROVIDER_ERROR"
    assert result.metadata.quality is None
    assert "secret-token" not in result.model_dump_json()
    assert result.execution_trace.steps[0].status == SkillStatus.FAILED


def test_pit_failure_is_not_hidden_as_partial(fiscal_context) -> None:
    market = fiscal_context.market.model_copy(
        update={
            "observations": (
                *fiscal_context.market.observations[:-1],
                fiscal_context.market.observations[-1].model_copy(
                    update={"date": date(2099, 1, 1)}
                ),
            ),
        }
    )
    context = fiscal_context.model_copy(update={"market": market})
    result = CompanyOverviewSkill().run_from_context(execution(context))
    assert result.metadata.status == SkillStatus.FAILED
    assert result.metadata.error.error_code == "PIT_VIOLATION"
    assert result.company_overview is None


def test_unsupported_metric_fails_before_provider_work() -> None:
    class NeverBuild:
        def build(self, **kwargs):
            raise AssertionError("unsupported metrics must not acquire data")

    result = FundamentalAnalysisSkill(NeverBuild()).run(
        ticker="NVDA",
        as_of_date=date(2026, 6, 30),
        metrics=["EBITDA"],
    )
    assert result.metadata.status == SkillStatus.FAILED
    assert result.metadata.error.error_code == "UNSUPPORTED_METRIC"
