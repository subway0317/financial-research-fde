"""Manifest and evidence sidecar derived exclusively from the structured report."""

from financial_research.reports.schemas import (
    ReportEvidenceArtifact,
    ReportManifest,
    ResearchReport,
)
from financial_research.schemas.agent import AgentStatus


def evidence_artifact(report: ResearchReport) -> ReportEvidenceArtifact:
    return ReportEvidenceArtifact(
        report_id=report.report_id,
        evidence_appendix=report.evidence_appendix,
        calculation_appendix=report.calculation_appendix,
    )


def build_manifest(report: ResearchReport) -> ReportManifest:
    runtime = report.runtime_metadata
    return ReportManifest(
        report_id=report.report_id,
        run_id=report.run_id,
        ticker=report.ticker,
        as_of_date=report.as_of_date,
        language=report.language,
        report_status=report.status,
        agent_status=AgentStatus(report.status.value),
        synthesis_readiness=report.synthesis_readiness,
        quality_status=report.quality_status,
        synthesis_call_count=runtime.synthesis_call_count,
        repair_count=runtime.repair_count,
        claim_count=sum(len(section.claims) for section in report.sections),
        evidence_count=len(report.evidence_appendix),
        calculation_count=len(report.calculation_appendix),
        provider=runtime.provider,
        model=runtime.model,
        synthesis_prompt_version=runtime.synthesis_prompt_version,
        created_at=runtime.created_at,
        integrity=report.integrity,
    )
