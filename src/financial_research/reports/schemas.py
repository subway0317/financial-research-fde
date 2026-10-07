"""Transport-independent v1 report, evidence, execution and manifest contracts."""

import re
from datetime import date as Date
from enum import StrEnum
from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import AwareDatetime, BeforeValidator, Field

from financial_research.schemas.agent import (
    AgentExecutionTrace,
    AgentStatus,
    GroundedClaim,
    LLMUsageMetadata,
    ResponseLanguage,
    SynthesisPayloadAudit,
)
from financial_research.schemas.base import CanonicalModel, NonEmpty, Ticker
from financial_research.schemas.quality import QualityReport, QualityStatus
from financial_research.schemas.skills import SynthesisReadiness
from financial_research.schemas.tools import CalculationProvenance, EvidenceReference

REPORT_VERSION: Final = "research-report-v1"
COMPILER_VERSION: Final = "report-compiler-v1"
BUNDLE_VERSION: Final = "research-report-bundle-v1"
PLAN_VERSION: Final = "deterministic-equity-report-plan-v1"

type ReportLanguage = Literal[ResponseLanguage.ENGLISH, ResponseLanguage.CHINESE]
type ReportID = Annotated[str, Field(pattern=r"^report:[0-9a-f]{64}$")]
type EvidenceDisplayAlias = Annotated[str, Field(pattern=r"^E[1-9][0-9]*$")]
type CalculationDisplayAlias = Annotated[str, Field(pattern=r"^C[1-9][0-9]*$")]
type SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def _calendar_date(value: object) -> Date:
    if type(value) is Date:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return Date.fromisoformat(value)
    raise ValueError("as_of_date must be YYYY-MM-DD")


class EquityResearchReportRequest(CanonicalModel):
    ticker: Ticker
    as_of_date: Annotated[Date, BeforeValidator(_calendar_date)]
    response_language: ReportLanguage = ResponseLanguage.ENGLISH


class ReportStatus(StrEnum):
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
    BLOCKED = "BLOCKED"


class ReportSectionID(StrEnum):
    SCOPE = "SCOPE"
    COMPANY = "COMPANY"
    FUNDAMENTALS = "FUNDAMENTALS"
    MARKET = "MARKET"
    QUALITY = "QUALITY"
    LIMITATIONS = "LIMITATIONS"
    EVIDENCE = "EVIDENCE"
    CALCULATIONS = "CALCULATIONS"
    AUDIT = "AUDIT"


class ReportSection(CanonicalModel):
    section_id: ReportSectionID
    claims: tuple[GroundedClaim, ...] = ()


class EvidenceAppendixEntry(CanonicalModel):
    display_alias: EvidenceDisplayAlias
    canonical_id: NonEmpty
    evidence: EvidenceReference


class CalculationAppendixEntry(CanonicalModel):
    display_alias: CalculationDisplayAlias
    canonical_id: NonEmpty
    provenance: CalculationProvenance
    result: str | None
    result_unit: str | None
    date: Date | None
    period_start: Date | None
    period_end: Date | None
    input_display_aliases: tuple[EvidenceDisplayAlias, ...]


class ReportRuntimeMetadata(CanonicalModel):
    created_at: AwareDatetime
    provider: NonEmpty
    model: NonEmpty
    plan_version: Literal["deterministic-equity-report-plan-v1"] = PLAN_VERSION
    planner_used: Literal[False] = False
    planner_call_count: Literal[0] = 0
    synthesis_call_count: Annotated[int, Field(ge=0, le=2)]
    repair_count: Annotated[int, Field(ge=0, le=1)]
    planner_prompt_version: None = None
    synthesis_prompt_version: NonEmpty
    report_compiler_version: Literal["report-compiler-v1"] = COMPILER_VERSION
    llm_usage: tuple[LLMUsageMetadata, ...]
    trace: AgentExecutionTrace
    synthesis_payload_audit: SynthesisPayloadAudit | None


class ReportIntegrity(CanonicalModel):
    algorithm: Literal["SHA-256"] = "SHA-256"
    semantic_hash: SHA256


class ResearchReport(CanonicalModel):
    report_version: Literal["research-report-v1"] = REPORT_VERSION
    report_id: ReportID
    run_id: UUID
    ticker: Ticker
    as_of_date: Date
    language: ReportLanguage
    status: ReportStatus
    selected_skill_id: Literal["equity_research"] = "equity_research"
    synthesis_readiness: SynthesisReadiness
    quality_status: QualityStatus
    quality: QualityReport
    sections: tuple[ReportSection, ...]
    limitations: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    evidence_appendix: tuple[EvidenceAppendixEntry, ...]
    calculation_appendix: tuple[CalculationAppendixEntry, ...]
    runtime_metadata: ReportRuntimeMetadata
    integrity: ReportIntegrity


class ReportEvidenceArtifact(CanonicalModel):
    report_version: Literal["research-report-v1"] = REPORT_VERSION
    report_id: ReportID
    evidence_appendix: tuple[EvidenceAppendixEntry, ...]
    calculation_appendix: tuple[CalculationAppendixEntry, ...]


class ReportFileHashes(CanonicalModel):
    report_json: SHA256 = Field(alias="report.json")
    report_markdown: SHA256 = Field(alias="report.md")
    evidence_json: SHA256 = Field(alias="evidence.json")


class ReportManifest(CanonicalModel):
    bundle_version: Literal["research-report-bundle-v1"] = BUNDLE_VERSION
    report_version: Literal["research-report-v1"] = REPORT_VERSION
    report_id: ReportID
    run_id: UUID
    ticker: Ticker
    as_of_date: Date
    language: ReportLanguage
    selected_skill_id: Literal["equity_research"] = "equity_research"
    report_status: ReportStatus
    agent_status: AgentStatus
    synthesis_readiness: SynthesisReadiness
    quality_status: QualityStatus
    planner_used: Literal[False] = False
    planner_call_count: Literal[0] = 0
    synthesis_call_count: Annotated[int, Field(ge=0, le=2)]
    repair_count: Annotated[int, Field(ge=0, le=1)]
    claim_count: Annotated[int, Field(ge=0)]
    evidence_count: Annotated[int, Field(ge=0)]
    calculation_count: Annotated[int, Field(ge=0)]
    provider: NonEmpty
    model: NonEmpty
    plan_version: Literal["deterministic-equity-report-plan-v1"] = PLAN_VERSION
    planner_prompt_version: None = None
    synthesis_prompt_version: NonEmpty
    report_compiler_version: Literal["report-compiler-v1"] = COMPILER_VERSION
    created_at: AwareDatetime
    integrity: ReportIntegrity
    file_hashes: ReportFileHashes | None = None


class EquityResearchReportResponse(CanonicalModel):
    report: ResearchReport
    markdown: str
    manifest_summary: ReportManifest
