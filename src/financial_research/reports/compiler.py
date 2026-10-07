"""Package validated claims verbatim. No synthesis, source access or financial arithmetic."""

from datetime import datetime
from uuid import UUID

from pydantic import ValidationError

from financial_research.reports.citations import appendices
from financial_research.reports.errors import ReportCompilationError
from financial_research.reports.identity import semantic_hash
from financial_research.reports.schemas import (
    PLAN_VERSION,
    ReportIntegrity,
    ReportRuntimeMetadata,
    ReportSection,
    ReportSectionID,
    ReportStatus,
    ResearchReport,
)
from financial_research.reports.validation import validate_report
from financial_research.schemas.agent import AgentIntent, GroundedResearchAnswer, LLMPhase


class ReportCompiler:
    def compile(
        self,
        answer: GroundedResearchAnswer,
        *,
        run_id: UUID,
        created_at: datetime,
        provider: str,
        model: str,
    ) -> ResearchReport:
        try:
            answer = GroundedResearchAnswer.model_validate(answer.model_dump())
            if (
                answer.plan.intent != AgentIntent.BROAD_RESEARCH
                or answer.used_skill_ids != ("equity_research",)
                or answer.planner_prompt_version != PLAN_VERSION
                or any(
                    usage.phase not in {LLMPhase.SYNTHESIS, LLMPhase.SYNTHESIS_REPAIR}
                    for usage in answer.llm_usage
                )
            ):
                raise ReportCompilationError("INVALID_REPORT_EXECUTION")
            evidence, calculations = appendices(answer)
            status = ReportStatus(answer.agent_status.value)
            section_ids = tuple(
                section
                for section in ReportSectionID
                if status != ReportStatus.BLOCKED
                or section
                not in {
                    ReportSectionID.COMPANY,
                    ReportSectionID.FUNDAMENTALS,
                    ReportSectionID.MARKET,
                }
            )
            report = ResearchReport(
                report_id="report:" + "0" * 64,
                run_id=run_id,
                ticker=answer.ticker,
                as_of_date=answer.as_of_date,
                language=answer.response_language,
                status=status,
                synthesis_readiness=answer.synthesis_readiness,
                quality_status=answer.quality.status,
                quality=answer.quality,
                sections=tuple(
                    ReportSection(
                        section_id=section,
                        claims=tuple(
                            claim for claim in answer.claims if claim.section.value == section.value
                        ),
                    )
                    for section in section_ids
                ),
                limitations=answer.limitations,
                blocking_reasons=answer.unavailable_context,
                evidence_appendix=evidence,
                calculation_appendix=calculations,
                runtime_metadata=ReportRuntimeMetadata(
                    created_at=created_at,
                    provider=answer.llm_usage[-1].provider if answer.llm_usage else provider,
                    model=answer.llm_usage[-1].model if answer.llm_usage else model,
                    synthesis_call_count=len(answer.llm_usage),
                    repair_count=sum(usage.repair_count for usage in answer.llm_usage),
                    synthesis_prompt_version=answer.synthesis_prompt_version,
                    llm_usage=answer.llm_usage,
                    trace=answer.trace,
                    synthesis_payload_audit=answer.synthesis_payload_audit,
                ),
                integrity=ReportIntegrity(semantic_hash="0" * 64),
            )
        except (ValidationError, ValueError):
            raise ReportCompilationError("INVALID_REPORT_INPUT") from None
        digest = semantic_hash(report)
        report = report.model_copy(
            update={
                "report_id": f"report:{digest}",
                "integrity": ReportIntegrity(semantic_hash=digest),
            }
        )
        validate_report(report)
        return report
