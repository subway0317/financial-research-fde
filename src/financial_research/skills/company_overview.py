"""Organize company state; financial values are supplied by the snapshot tool."""

from datetime import date

from financial_research.schemas.skills import (
    CompanyOverviewResult,
    CompanyOverviewSection,
    SkillDefinition,
    SkillInput,
    SkillStatus,
)
from financial_research.schemas.tools import ResultStatus
from financial_research.skills.base import BaseSkill
from financial_research.skills.context import SkillExecutionContext
from financial_research.skills.evidence import merge_calculations, merge_evidence, merge_limitations


class CompanyOverviewSkill(BaseSkill[CompanyOverviewResult]):
    definition = SkillDefinition(
        skill_id="company_overview",
        version="1.0",
        name="Company overview",
        description="Organize legally available company identity, market state and fundamentals.",
        required_tools=("get_company_snapshot",),
        input_type="financial_research.schemas.skills.SkillInput",
        output_type="financial_research.schemas.skills.CompanyOverviewResult",
        capabilities=("company_identity", "current_research_state"),
    )
    result_type = CompanyOverviewResult

    def run(self, *, ticker: str, as_of_date: date) -> CompanyOverviewResult:
        return self._run(SkillInput(ticker=ticker, as_of_date=as_of_date), self.run_from_context)

    def run_from_context(self, execution: SkillExecutionContext) -> CompanyOverviewResult:
        def organize() -> CompanyOverviewResult:
            snapshot = execution.snapshot()
            status = SkillStatus.SUCCESS
            if snapshot.latest_close is None or snapshot.latest_market_session is None:
                status = SkillStatus.UNAVAILABLE
            elif (
                any(metric.status == ResultStatus.UNAVAILABLE for metric in snapshot.fundamentals)
                or any(
                    window.status == ResultStatus.UNAVAILABLE for window in snapshot.market_windows
                )
                or any(
                    value is None for value in snapshot.latest_market_features.model_dump().values()
                )
            ):
                status = SkillStatus.PARTIAL
            return CompanyOverviewResult(
                metadata=self.metadata(execution, status),
                company_overview=CompanyOverviewSection(
                    company=snapshot.company,
                    latest_market_session=snapshot.latest_market_session,
                    latest_close=snapshot.latest_close,
                    market_windows=snapshot.market_windows,
                    latest_market_features=snapshot.latest_market_features,
                    fundamentals=snapshot.fundamentals,
                    evidence_ids=tuple(sorted(ref.evidence_id for ref in snapshot.evidence)),
                ),
                evidence_index=merge_evidence(snapshot.evidence),
                calculation_provenance=merge_calculations(snapshot.calculation_provenance),
                limitations=merge_limitations(
                    snapshot.limitations,
                    (reason for metric in snapshot.fundamentals for reason in metric.limitations),
                ),
                execution_trace=execution.trace(),
            )

        return self._execute(execution, organize)
