"""Audit the authoritative quality result; do not invent additional data rules."""

from datetime import date

from financial_research.schemas.quality import QualityStatus, Severity
from financial_research.schemas.skills import (
    ResearchQualityAuditResult,
    ResearchQualitySection,
    SkillDefinition,
    SkillInput,
    SkillStatus,
)
from financial_research.skills.base import BaseSkill
from financial_research.skills.context import SkillExecutionContext
from financial_research.skills.errors import CriticalQualityError, safe_error
from financial_research.skills.evidence import merge_calculations, merge_evidence, merge_limitations


class ResearchQualityAuditSkill(BaseSkill[ResearchQualityAuditResult]):
    definition = SkillDefinition(
        skill_id="research_quality_audit",
        version="1.0",
        name="Research quality audit",
        description="Organize authoritative issues, objective freshness and source limitations.",
        required_tools=("inspect_research_quality",),
        input_type="financial_research.schemas.skills.SkillInput",
        output_type="financial_research.schemas.skills.ResearchQualityAuditResult",
        capabilities=("quality_audit", "freshness_metadata", "provenance_audit"),
    )
    result_type = ResearchQualityAuditResult
    allows_failed_quality = True

    def run(self, *, ticker: str, as_of_date: date) -> ResearchQualityAuditResult:
        return self._run(SkillInput(ticker=ticker, as_of_date=as_of_date), self.run_from_context)

    def run_from_context(self, execution: SkillExecutionContext) -> ResearchQualityAuditResult:
        def organize() -> ResearchQualityAuditResult:
            quality = execution.quality()
            failed = quality.overall_status == QualityStatus.FAIL
            error = safe_error(CriticalQualityError(), self.definition.skill_id) if failed else None
            return ResearchQualityAuditResult(
                metadata=self.metadata(
                    execution, SkillStatus.FAILED if failed else SkillStatus.SUCCESS, error
                ),
                research_quality=ResearchQualitySection(
                    overall_status=quality.overall_status,
                    issues=quality.issues,
                    critical_issues=tuple(
                        issue for issue in quality.issues if issue.severity == Severity.ERROR
                    ),
                    warnings=tuple(
                        issue for issue in quality.issues if issue.severity == Severity.WARNING
                    ),
                    latest_market_session=quality.latest_market_session,
                    market_age_calendar_days=quality.market_age_calendar_days,
                    latest_fundamental_available_date=quality.latest_fundamental_available_date,
                    fundamental_age_calendar_days=quality.fundamental_age_calendar_days,
                    available_registered_metrics=quality.available_registered_metrics,
                    missing_registered_metrics=quality.missing_registered_metrics,
                    provenance_summary=quality.provenance_summary,
                    evidence_ids=tuple(sorted(ref.evidence_id for ref in quality.evidence)),
                ),
                evidence_index=merge_evidence(quality.evidence),
                calculation_provenance=merge_calculations(quality.calculation_provenance),
                limitations=merge_limitations(
                    quality.limitations, (error.error_code,) if error else ()
                ),
                execution_trace=execution.trace(),
            )

        return self._execute(execution, organize)
