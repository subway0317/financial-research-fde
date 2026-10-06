from datetime import UTC, date, datetime

import pytest

from financial_research.company.service import CompanyService
from financial_research.exceptions import DataValidationError, PITViolationError, ProviderError
from financial_research.fundamentals.service import FundamentalService
from financial_research.market.service import MarketService
from financial_research.research import ResearchContextBuilder
from financial_research.schemas.fundamentals import (
    FundamentalResearch,
    FundamentalSourceDataset,
    SourceFundamentalFact,
)
from financial_research.schemas.market import MarketDataset
from financial_research.schemas.quality import QualityIssue, QualityReport, QualityStatus, Severity
from financial_research.schemas.skills import (
    ResearchEvidencePackage,
    SkillStatus,
    SynthesisReadiness,
    TraceAction,
)
from financial_research.skills import (
    EquityResearchSkill,
    ResearchQualityAuditSkill,
    SkillExecutionContext,
    create_skill_registry,
)


def execute(context, **kwargs):
    shared = SkillExecutionContext(
        ticker=context.ticker,
        as_of_date=context.as_of_date,
        research_context=context,
    )
    return EquityResearchSkill().run_from_context(shared, **kwargs)


def complete_context(context, quality):
    """Synthetic support facts and injected gate report isolate orchestration policy."""
    extra = tuple(
        observation.model_copy(update={"metric": replacement})
        for original, replacement in (
            ("revenue", "operating_cash_flow"),
            ("cash_and_equivalents", "stockholders_equity"),
        )
        for observation in context.fundamentals.observations
        if observation.metric == original
    )
    facts = (*context.fundamentals.observations, *extra)
    return context.model_copy(
        update={
            "fundamentals": FundamentalResearch(
                observations=facts,
                provenance=tuple(o.provenance_record() for o in facts),
            ),
            "quality": quality,
        }
    )


def test_default_registry_metadata_and_composite_evidence(fiscal_context) -> None:
    registry = create_skill_registry()
    assert {item.skill_id for item in registry.list()} == {
        "company_overview",
        "fundamental_analysis",
        "market_analysis",
        "research_quality_audit",
        "equity_research",
    }
    assert registry.get("equity_research").definition.required_skills == (
        "company_overview",
        "fundamental_analysis",
        "market_analysis",
        "research_quality_audit",
    )
    package = execute(fiscal_context)
    assert isinstance(package, ResearchEvidencePackage)
    assert package.metadata.status == SkillStatus.PARTIAL
    assert package.synthesis_readiness == SynthesisReadiness.READY_WITH_WARNINGS
    assert package.metadata.quality == fiscal_context.quality
    assert len(package.subskill_metadata) == 4
    for section in (
        package.company_overview,
        package.fundamental_analysis,
        package.market_analysis,
        package.research_quality,
    ):
        assert section is not None
        assert set(section.evidence_ids) <= package.evidence_index.keys()
        assert not hasattr(section, "evidence")
    for calc in package.calculation_provenance:
        assert calc.input_evidence_ids
        assert set(calc.input_evidence_ids) <= package.evidence_index.keys()
    assert len(package.calculation_provenance) == len(
        {calc.evidence_id for calc in package.calculation_provenance}
    )
    assert {issue.code for issue in fiscal_context.quality.issues} <= set(package.limitations)
    assert "NO_CURRENT_OBSERVATION" in package.limitations
    assert package.limitations == tuple(sorted(set(package.limitations)))
    assert list(package.evidence_index) == sorted(package.evidence_index)


@pytest.mark.parametrize(
    "quality,readiness",
    [
        (QualityReport(status=QualityStatus.PASS), SynthesisReadiness.READY),
        (
            QualityReport.from_issues(
                (
                    QualityIssue(
                        code="VINTAGE",
                        severity=Severity.WARNING,
                        message="Retrieved source vintage.",
                    ),
                )
            ),
            SynthesisReadiness.READY_WITH_WARNINGS,
        ),
    ],
)
def test_success_and_synthesis_gate_preserve_quality(fiscal_context, quality, readiness) -> None:
    context = complete_context(fiscal_context, quality)
    package = execute(context, metrics=["revenue"])
    assert package.metadata.status == SkillStatus.SUCCESS
    assert package.synthesis_readiness == readiness
    assert package.metadata.quality == quality
    assert package.research_quality.overall_status == quality.status


def test_quality_fail_stops_financial_work_and_returns_diagnostics(
    fiscal_context, monkeypatch
) -> None:
    report = QualityReport.from_issues(
        (
            *fiscal_context.quality.issues,
            QualityIssue(code="CONFLICT", severity=Severity.ERROR, message="Source conflict."),
        )
    )
    context = fiscal_context.model_copy(update={"quality": report})

    def forbidden(*args, **kwargs):
        raise AssertionError("quality FAIL must gate financial tools")

    for name in ("get_company_snapshot", "analyze_fundamental_trends", "summarize_market_behavior"):
        monkeypatch.setattr(f"financial_research.skills.context.{name}", forbidden)
    package = execute(context)
    assert package.metadata.status == SkillStatus.FAILED
    assert package.synthesis_readiness == SynthesisReadiness.NOT_READY
    assert package.metadata.error.error_code == "CRITICAL_QUALITY_FAILURE"
    assert package.company_overview is None
    assert package.fundamental_analysis is None
    assert package.market_analysis is None
    assert package.research_quality.critical_issues[-1].code == "CONFLICT"
    assert len(package.subskill_metadata) == 1
    assert (
        next(
            step
            for step in package.execution_trace.steps
            if step.action_type == TraceAction.QUALITY_GATE
        ).status
        == SkillStatus.FAILED
    )


@pytest.mark.parametrize(
    "options",
    [
        {"metrics": ["stockholders_equity"]},
        {"lookback_sessions": 100},
    ],
)
def test_missing_core_evidence_is_unavailable_not_ready(fiscal_context, options) -> None:
    package = execute(fiscal_context, **options)
    assert package.metadata.status == SkillStatus.UNAVAILABLE
    assert package.metadata.error is None
    assert package.synthesis_readiness == SynthesisReadiness.NOT_READY
    assert package.company_overview is not None
    assert package.research_quality is not None


@pytest.mark.parametrize(
    "exception,code",
    [
        (ProviderError("secret-provider-body"), "PROVIDER_ERROR"),
        (PITViolationError("future filing"), "PIT_VIOLATION"),
        (DataValidationError("raw invalid payload"), "DATA_VALIDATION_ERROR"),
    ],
)
def test_acquisition_failure_cannot_be_partial(exception, code) -> None:
    class Broken:
        def build(self, **kwargs):
            raise exception

    package = EquityResearchSkill(Broken()).run(ticker="NVDA", as_of_date=date(2026, 6, 30))
    assert package.metadata.status == SkillStatus.FAILED
    assert package.metadata.error.error_code == code
    assert package.synthesis_readiness == SynthesisReadiness.NOT_READY
    assert package.company_overview is None
    assert package.evidence_index == {}
    assert "secret-provider-body" not in package.model_dump_json()


def test_evidence_collision_is_explicit_failed_package(fiscal_context) -> None:
    class ConflictingAudit(ResearchQualityAuditSkill):
        def run_from_context(self, execution):
            result = super().run_from_context(execution)
            market_id = next(
                key for key, ref in result.evidence_index.items() if ref.metric == "close"
            )
            corrupted = {
                **result.evidence_index,
                market_id: result.evidence_index[market_id].model_copy(update={"value": "999"}),
            }
            return result.model_copy(update={"evidence_index": corrupted})

    skill = EquityResearchSkill(research_quality=ConflictingAudit())
    shared = SkillExecutionContext(
        ticker=fiscal_context.ticker,
        as_of_date=fiscal_context.as_of_date,
        research_context=fiscal_context,
    )
    result = skill.run_from_context(shared)
    assert result.metadata.status == SkillStatus.FAILED
    assert result.metadata.error.error_code == "EVIDENCE_INTEGRITY_ERROR"
    assert result.synthesis_readiness == SynthesisReadiness.NOT_READY
    assert result.evidence_index == {}
    assert any(
        step.action_type == TraceAction.EVIDENCE_MERGE and step.status == SkillStatus.FAILED
        for step in result.execution_trace.steps
    )


def test_missing_evidence_reference_is_integrity_failure(fiscal_context) -> None:
    class OrphanAudit(ResearchQualityAuditSkill):
        def run_from_context(self, execution):
            result = super().run_from_context(execution)
            section = result.research_quality.model_copy(update={"evidence_ids": ("absent-id",)})
            return result.model_copy(update={"research_quality": section})

    skill = EquityResearchSkill(research_quality=OrphanAudit())
    shared = SkillExecutionContext(
        ticker=fiscal_context.ticker,
        as_of_date=fiscal_context.as_of_date,
        research_context=fiscal_context,
    )
    result = skill.run_from_context(shared)
    assert result.metadata.status == SkillStatus.FAILED
    assert result.metadata.error.error_code == "EVIDENCE_INTEGRITY_ERROR"


def test_normalized_determinism_and_objective_trace_order(fiscal_context) -> None:
    first = execute(fiscal_context)
    facts = tuple(
        o.model_copy(update={"retrieved_at": datetime(2040, 1, 1, tzinfo=UTC)})
        for o in fiscal_context.fundamentals.observations
    )
    later = fiscal_context.model_copy(
        update={
            "generated_at": datetime(2040, 1, 1, tzinfo=UTC),
            "fundamentals": fiscal_context.fundamentals.model_copy(update={"observations": facts}),
        }
    )
    second = execute(later)
    assert first.metadata.execution_id != second.metadata.execution_id
    assert first.normalized_business_json() == second.normalized_business_json()
    assert first.evidence_index == second.evidence_index
    assert [(step.action_type, step.target) for step in first.execution_trace.steps] == [
        (TraceAction.CONTEXT_REUSE, "research_context"),
        (TraceAction.QUALITY_GATE, "research_context"),
        (TraceAction.TOOL_CALL, "get_company_snapshot"),
        (TraceAction.SKILL_CALL, "company_overview"),
        (TraceAction.TOOL_CALL, "analyze_fundamental_trends"),
        (TraceAction.SKILL_CALL, "fundamental_analysis"),
        (TraceAction.TOOL_REUSE, "get_company_snapshot.market_window_60"),
        (TraceAction.SKILL_CALL, "market_analysis"),
        (TraceAction.TOOL_CALL, "inspect_research_quality"),
        (TraceAction.SKILL_CALL, "research_quality_audit"),
        (TraceAction.EVIDENCE_MERGE, "evidence_index"),
        (TraceAction.PACKAGE_ASSEMBLY, "equity_research"),
        (TraceAction.SKILL_CALL, "equity_research"),
    ]
    assert all("reasoning" not in step.model_dump() for step in first.execution_trace.steps)


def test_composite_builds_once_and_reuses_all_provider_state(fiscal_context, monkeypatch) -> None:
    counts = {"company": 0, "market": 0, "fundamentals": 0, "build": 0}
    seen_contexts = []

    class Provider:
        def get_company(self, ticker):
            counts["company"] += 1
            return fiscal_context.company

        def get_market(self, ticker, start, end):
            counts["market"] += 1
            return MarketDataset(
                observations=fiscal_context.market.observations,
                metadata=fiscal_context.market.metadata,
            )

        def get_fundamentals(self, company):
            counts["fundamentals"] += 1
            return FundamentalSourceDataset(
                facts=tuple(
                    SourceFundamentalFact.model_validate(o.model_dump(exclude={"available_date"}))
                    for o in fiscal_context.fundamentals.observations
                ),
                provenance=fiscal_context.fundamentals.provenance[0],
            )

    provider = Provider()
    core = ResearchContextBuilder(
        company_service=CompanyService(provider),
        market_service=MarketService(provider),
        fundamental_service=FundamentalService(provider),
    )

    class CountingBuilder:
        def build(self, **kwargs):
            counts["build"] += 1
            return core.build(**kwargs)

    import financial_research.skills.context as context_module

    for name in ("get_company_snapshot", "analyze_fundamental_trends", "inspect_research_quality"):
        original = getattr(context_module, name)

        def spy(context, _original=original, **kwargs):
            seen_contexts.append(id(context))
            return _original(context, **kwargs)

        monkeypatch.setattr(context_module, name, spy)

    skill = EquityResearchSkill(CountingBuilder())
    result = skill.run(ticker=fiscal_context.ticker, as_of_date=fiscal_context.as_of_date)
    assert result.metadata.status == SkillStatus.PARTIAL
    assert counts == {"company": 1, "market": 1, "fundamentals": 1, "build": 1}
    assert len(seen_contexts) == 3 and len(set(seen_contexts)) == 1
    second = skill.run(ticker=fiscal_context.ticker, as_of_date=fiscal_context.as_of_date)
    assert counts == {"company": 2, "market": 2, "fundamentals": 2, "build": 2}
    assert result.metadata.execution_id != second.metadata.execution_id
    assert result.normalized_business_json() == second.normalized_business_json()


def test_bound_context_cannot_change_after_cached_tool_work(fiscal_context) -> None:
    shared = SkillExecutionContext(
        ticker=fiscal_context.ticker,
        as_of_date=fiscal_context.as_of_date,
        research_context=fiscal_context,
    )
    shared.snapshot()
    shared.research_context = fiscal_context.model_copy()
    with pytest.raises(DataValidationError):
        shared.require_context()
