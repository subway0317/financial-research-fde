"""Organize the shared trends result without repeating per-metric calculations."""

from datetime import date

from financial_research.schemas.skills import (
    FundamentalAnalysisInput,
    FundamentalAnalysisResult,
    FundamentalAnalysisSection,
    MetricAnalysis,
    SkillDefinition,
    SkillStatus,
)
from financial_research.schemas.tools import ResultStatus
from financial_research.skills.base import BaseSkill
from financial_research.skills.context import SkillExecutionContext
from financial_research.skills.evidence import merge_calculations, merge_evidence, merge_limitations
from financial_research.tools.common import metric_names


class FundamentalAnalysisSkill(BaseSkill[FundamentalAnalysisResult]):
    definition = SkillDefinition(
        skill_id="fundamental_analysis",
        version="1.0",
        name="Fundamental analysis",
        description="Organize registered, PIT-safe comparable-period trend evidence.",
        required_tools=("analyze_fundamental_trends",),
        input_type="financial_research.schemas.skills.FundamentalAnalysisInput",
        output_type="financial_research.schemas.skills.FundamentalAnalysisResult",
        capabilities=("fundamental_trends", "legal_year_over_year_comparisons"),
    )
    result_type = FundamentalAnalysisResult

    def run(
        self,
        *,
        ticker: str,
        as_of_date: date,
        metrics: list[str] | None = None,
    ) -> FundamentalAnalysisResult:
        request = FundamentalAnalysisInput(ticker=ticker, as_of_date=as_of_date, metrics=metrics)
        return self._run(
            request,
            lambda context: self.run_from_context(context, metrics=request.metrics),
            preflight=lambda: metric_names(request.metrics),
        )

    def run_from_context(
        self,
        execution: SkillExecutionContext,
        *,
        metrics: list[str] | None = None,
    ) -> FundamentalAnalysisResult:
        def organize() -> FundamentalAnalysisResult:
            trends = execution.trends(metrics)
            available = tuple(
                row.metric
                for row in trends.metrics
                if row.comparison_status == ResultStatus.AVAILABLE
            )
            unavailable = tuple(
                row.metric
                for row in trends.metrics
                if row.comparison_status == ResultStatus.UNAVAILABLE
            )
            status = (
                SkillStatus.UNAVAILABLE
                if not available
                else SkillStatus.PARTIAL
                if unavailable
                else SkillStatus.SUCCESS
            )
            summaries = tuple(
                MetricAnalysis.model_validate(
                    {
                        **row.model_dump(exclude={"evidence", "calculation_provenance"}),
                        "evidence_ids": tuple(sorted(ref.evidence_id for ref in row.evidence)),
                        "calculation_ids": tuple(
                            sorted(calc.evidence_id for calc in row.calculation_provenance)
                        ),
                    }
                )
                for row in trends.metrics
            )
            return FundamentalAnalysisResult(
                metadata=self.metadata(execution, status),
                fundamental_analysis=FundamentalAnalysisSection(
                    metrics=summaries,
                    available_metrics=available,
                    unavailable_metrics=unavailable,
                    evidence_ids=tuple(sorted(ref.evidence_id for ref in trends.evidence)),
                ),
                evidence_index=merge_evidence(trends.evidence),
                calculation_provenance=merge_calculations(trends.calculation_provenance),
                limitations=merge_limitations(trends.limitations),
                execution_trace=execution.trace(),
            )

        return self._execute(execution, organize)
