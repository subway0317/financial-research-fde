"""Fixed four-skill workflow; no planning, financial recalculation or synthesis."""

from datetime import date

from financial_research.schemas.quality import QualityStatus
from financial_research.schemas.skills import (
    CompanyOverviewResult,
    EquityResearchInput,
    FundamentalAnalysisResult,
    MarketAnalysisResult,
    ResearchEvidencePackage,
    ResearchQualityAuditResult,
    SkillDefinition,
    SkillErrorMetadata,
    SkillResult,
    SkillStatus,
    SynthesisReadiness,
    TraceAction,
)
from financial_research.schemas.tools import CalculationProvenance, EvidenceReference
from financial_research.skills.base import BaseSkill
from financial_research.skills.company_overview import CompanyOverviewSkill
from financial_research.skills.context import SkillExecutionContext
from financial_research.skills.errors import CriticalQualityError, safe_error
from financial_research.skills.evidence import (
    merge_calculations,
    merge_evidence,
    merge_limitations,
    validate_evidence,
)
from financial_research.skills.fundamental_analysis import FundamentalAnalysisSkill
from financial_research.skills.market_analysis import MarketAnalysisSkill
from financial_research.skills.research_quality import ResearchQualityAuditSkill
from financial_research.tools.common import context_limitations, metric_names
from financial_research.tools.service import ContextBuilder


class EquityResearchSkill(BaseSkill[ResearchEvidencePackage]):
    definition = SkillDefinition(
        skill_id="equity_research",
        version="1.0",
        name="Equity research evidence",
        description="Assemble a quality-gated evidence package through a fixed research workflow.",
        required_tools=(
            "get_company_snapshot",
            "analyze_fundamental_trends",
            "summarize_market_behavior",
            "inspect_research_quality",
        ),
        required_skills=(
            "company_overview",
            "fundamental_analysis",
            "market_analysis",
            "research_quality_audit",
        ),
        input_type="financial_research.schemas.skills.EquityResearchInput",
        output_type="financial_research.schemas.skills.ResearchEvidencePackage",
        capabilities=("equity_evidence_package", "controlled_orchestration", "synthesis_readiness"),
    )
    result_type = ResearchEvidencePackage
    allows_failed_quality = True  # The composite records its explicit gate before stopping.

    def __init__(
        self,
        builder: ContextBuilder | None = None,
        *,
        company_overview: CompanyOverviewSkill | None = None,
        fundamental_analysis: FundamentalAnalysisSkill | None = None,
        market_analysis: MarketAnalysisSkill | None = None,
        research_quality: ResearchQualityAuditSkill | None = None,
    ) -> None:
        super().__init__(builder)
        self._company = company_overview or CompanyOverviewSkill()
        self._fundamental = fundamental_analysis or FundamentalAnalysisSkill()
        self._market = market_analysis or MarketAnalysisSkill()
        self._quality = research_quality or ResearchQualityAuditSkill()

    def run(
        self,
        *,
        ticker: str,
        as_of_date: date,
        metrics: list[str] | None = None,
        lookback_sessions: int = 60,
    ) -> ResearchEvidencePackage:
        request = EquityResearchInput(
            ticker=ticker,
            as_of_date=as_of_date,
            metrics=metrics,
            lookback_sessions=lookback_sessions,
        )
        return self._run(
            request,
            lambda execution: self.run_from_context(
                execution,
                metrics=request.metrics,
                lookback_sessions=request.lookback_sessions,
            ),
            preflight=lambda: metric_names(request.metrics),
        )

    def _failed(self, execution: SkillExecutionContext, exc: Exception) -> ResearchEvidencePackage:
        execution.record(
            TraceAction.PACKAGE_ASSEMBLY,
            self.definition.skill_id,
            SkillStatus.FAILED,
            error_code=safe_error(exc, self.definition.skill_id).error_code,
        )
        return super()._failed(execution, exc)

    def run_from_context(
        self,
        execution: SkillExecutionContext,
        *,
        metrics: list[str] | None = None,
        lookback_sessions: int = 60,
    ) -> ResearchEvidencePackage:
        def workflow() -> ResearchEvidencePackage:
            request = EquityResearchInput(
                ticker=execution.ticker,
                as_of_date=execution.as_of_date,
                metrics=metrics,
                lookback_sessions=lookback_sessions,
            )
            metric_names(request.metrics)
            context = execution.require_context()
            failed_quality = context.quality.status == QualityStatus.FAIL
            execution.record(
                TraceAction.QUALITY_GATE,
                "research_context",
                SkillStatus.FAILED if failed_quality else SkillStatus.SUCCESS,
                error_code="CRITICAL_QUALITY_FAILURE" if failed_quality else None,
            )
            if failed_quality:
                audit = self._quality.run_from_context(execution)
                return self._assemble(
                    execution,
                    audit=audit,
                    error=safe_error(CriticalQualityError(), self.definition.skill_id),
                )
            company = self._company.run_from_context(execution)
            if company.metadata.status == SkillStatus.FAILED:
                return self._assemble(execution, company=company, error=company.metadata.error)
            fundamental = self._fundamental.run_from_context(execution, metrics=request.metrics)
            if fundamental.metadata.status == SkillStatus.FAILED:
                return self._assemble(
                    execution,
                    company=company,
                    fundamental=fundamental,
                    error=fundamental.metadata.error,
                )
            market = self._market.run_from_context(
                execution, lookback_sessions=request.lookback_sessions
            )
            if market.metadata.status == SkillStatus.FAILED:
                return self._assemble(
                    execution,
                    company=company,
                    fundamental=fundamental,
                    market=market,
                    error=market.metadata.error,
                )
            audit = self._quality.run_from_context(execution)
            return self._assemble(
                execution,
                company=company,
                fundamental=fundamental,
                market=market,
                audit=audit,
                error=audit.metadata.error,
            )

        return self._execute(execution, workflow)

    def _assemble(
        self,
        execution: SkillExecutionContext,
        *,
        company: CompanyOverviewResult | None = None,
        fundamental: FundamentalAnalysisResult | None = None,
        market: MarketAnalysisResult | None = None,
        audit: ResearchQualityAuditResult | None = None,
        error: SkillErrorMetadata | None = None,
    ) -> ResearchEvidencePackage:
        results: tuple[SkillResult, ...] = tuple(
            result for result in (company, fundamental, market, audit) if result is not None
        )

        def aggregate() -> tuple[dict[str, EvidenceReference], tuple[CalculationProvenance, ...]]:
            index = merge_evidence(*(result.evidence_index.values() for result in results))
            calculations = merge_calculations(
                *(result.calculation_provenance for result in results)
            )
            referenced_ids: list[str] = []
            for section in (
                company.company_overview if company else None,
                fundamental.fundamental_analysis if fundamental else None,
                market.market_analysis if market else None,
                audit.research_quality if audit else None,
            ):
                if section is not None:
                    referenced_ids.extend(section.evidence_ids)
            if fundamental and fundamental.fundamental_analysis:
                for metric in fundamental.fundamental_analysis.metrics:
                    referenced_ids.extend(metric.evidence_ids)
            validate_evidence(index, calculations, referenced_ids)
            return index, calculations

        index, calculations = execution.call(
            TraceAction.EVIDENCE_MERGE, "evidence_index", aggregate
        )
        context = execution.require_context()
        limitations = merge_limitations(
            context_limitations(context),
            *(result.limitations for result in results),
            (error.error_code,) if error else (),
        )
        statuses = tuple(result.metadata.status for result in results)
        if error is not None or SkillStatus.FAILED in statuses:
            status, readiness = SkillStatus.FAILED, SynthesisReadiness.NOT_READY
        elif len(results) != 4 or SkillStatus.UNAVAILABLE in statuses:
            status, readiness = SkillStatus.UNAVAILABLE, SynthesisReadiness.NOT_READY
        else:
            status = SkillStatus.PARTIAL if SkillStatus.PARTIAL in statuses else SkillStatus.SUCCESS
            readiness = (
                SynthesisReadiness.READY_WITH_WARNINGS
                if context.quality.status == QualityStatus.PASS_WITH_WARNINGS
                or status == SkillStatus.PARTIAL
                or limitations
                else SynthesisReadiness.READY
            )
        execution.record(
            TraceAction.PACKAGE_ASSEMBLY,
            self.definition.skill_id,
            status,
            error_code=error.error_code if error else None,
        )
        return ResearchEvidencePackage(
            metadata=self.metadata(execution, status, error),
            synthesis_readiness=readiness,
            company_overview=company.company_overview if company else None,
            fundamental_analysis=fundamental.fundamental_analysis if fundamental else None,
            market_analysis=market.market_analysis if market else None,
            research_quality=audit.research_quality if audit else None,
            subskill_metadata=tuple(result.metadata for result in results),
            evidence_index=index,
            calculation_provenance=calculations,
            limitations=limitations,
            execution_trace=execution.trace(),
        )
