"""Public contracts deliberately exclude session prices and market input sequences."""

from datetime import date as Date
from typing import Annotated, Literal

from pydantic import Field, model_validator

from financial_research.public_research.policy import is_market_source
from financial_research.reports.schemas import (
    SHA256,
    CalculationAppendixEntry,
    EvidenceAppendixEntry,
    ReportManifest,
    ResearchReport,
)
from financial_research.schemas.agent import (
    AgentExecutionTrace,
    AgentPlan,
    AgentStatus,
    GroundedClaim,
    LLMUsageMetadata,
    ResponseLanguage,
    SynthesisPayloadAudit,
)
from financial_research.schemas.base import CanonicalModel, NonEmpty, Ticker
from financial_research.schemas.quality import QualityReport
from financial_research.schemas.skills import SynthesisReadiness
from financial_research.schemas.tools import (
    CalculationProvenance,
    CompanySnapshotResult,
    EvidenceReference,
    FundamentalTrendResult,
    MarketBehaviorResult,
    MetricTrendResult,
    PeriodComparisonResult,
    ResearchQualityResult,
    ToolResult,
)

type ProjectionVersion = Literal["public-research-projection-v1"]
type IntegrityScope = Literal["INTERNAL_RESEARCH_REPORT"]


class PublicEvidenceReference(EvidenceReference):
    disclosure: Literal["FULL_FACT", "MARKET_INPUT_SUMMARY"]
    observation_count: Annotated[int, Field(ge=0)] | None = None
    input_range_start: Date | None = None
    input_range_end: Date | None = None
    internal_input_digest: SHA256 | None = None

    @model_validator(mode="after")
    def disclosure_boundary(self) -> "PublicEvidenceReference":
        if self.disclosure == "MARKET_INPUT_SUMMARY":
            if (
                self.value is not None
                or self.date is not None
                or "#" in self.source_reference
                or not self.evidence_id.startswith("public-market-summary:")
                or self.observation_count is None
                or self.internal_input_digest is None
                or self.filed_at is not None
                or self.available_date is not None
            ):
                raise ValueError("market summaries cannot contain session source facts")
        elif is_market_source(self):
            raise ValueError("session market source facts are internal only")
        return self


class PublicInputSummary(CanonicalModel):
    input_count: Annotated[int, Field(ge=0)]
    withheld_market_input_count: Annotated[int, Field(ge=0)]
    input_range_start: Date | None
    input_range_end: Date | None
    input_kind: Literal["SESSION_MARKET_OBSERVATIONS", "NON_MARKET_OR_DERIVED_FACTS"]
    input_metrics: tuple[NonEmpty, ...]
    internal_input_digest: SHA256

    @model_validator(mode="after")
    def accounting(self) -> "PublicInputSummary":
        if self.withheld_market_input_count > self.input_count:
            raise ValueError("withheld inputs cannot exceed total inputs")
        if (self.withheld_market_input_count > 0) != (
            self.input_kind == "SESSION_MARKET_OBSERVATIONS"
        ):
            raise ValueError("input kind must match the withheld market input count")
        if (self.input_range_start is None) != (self.input_range_end is None) or (
            self.input_range_start is not None
            and self.input_range_end is not None
            and self.input_range_start > self.input_range_end
        ):
            raise ValueError("input date range must be ordered and complete")
        return self


class PublicCalculationProvenance(CalculationProvenance):
    metric: NonEmpty
    result: str | None
    unit: str | None
    methodology: NonEmpty
    input_summary: PublicInputSummary


def _references_resolve(
    evidence: tuple[PublicEvidenceReference, ...],
    calculations: tuple[PublicCalculationProvenance, ...],
) -> None:
    index = {ref.evidence_id: ref for ref in evidence}
    if len(index) != len(evidence):
        raise ValueError("public evidence IDs must be unique")
    for calc in calculations:
        if calc.evidence_id not in index or not set(calc.input_evidence_ids) <= index.keys():
            raise ValueError("public calculation references must resolve")
        if any(index[key].disclosure == "MARKET_INPUT_SUMMARY" for key in calc.input_evidence_ids):
            raise ValueError("market input sequences cannot be public calculation links")
        if len(calc.input_evidence_ids) != (
            calc.input_summary.input_count - calc.input_summary.withheld_market_input_count
        ):
            raise ValueError("public input summary must account for all internal inputs")


class PublicEvidenceAppendixEntry(EvidenceAppendixEntry):
    evidence: PublicEvidenceReference


class PublicCalculationAppendixEntry(CalculationAppendixEntry):
    provenance: PublicCalculationProvenance


class PublicResearchReport(ResearchReport):
    projection_version: ProjectionVersion = "public-research-projection-v1"
    integrity_scope: IntegrityScope = "INTERNAL_RESEARCH_REPORT"
    evidence_appendix: tuple[PublicEvidenceAppendixEntry, ...]
    calculation_appendix: tuple[PublicCalculationAppendixEntry, ...]

    @model_validator(mode="after")
    def public_integrity(self) -> "PublicResearchReport":
        _references_resolve(
            tuple(entry.evidence for entry in self.evidence_appendix),
            tuple(entry.provenance for entry in self.calculation_appendix),
        )
        aliases = {entry.canonical_id: entry.display_alias for entry in self.evidence_appendix}
        if any(
            entry.canonical_id != entry.evidence.evidence_id for entry in self.evidence_appendix
        ):
            raise ValueError("public evidence canonical IDs must match")
        if len(set(aliases.values())) != len(self.evidence_appendix):
            raise ValueError("public evidence aliases must be unique")
        if any(
            not set(claim.evidence_ids) <= aliases.keys()
            for section in self.sections
            for claim in section.claims
        ):
            raise ValueError("public claim citations must resolve")
        for calc in self.calculation_appendix:
            if calc.canonical_id != calc.provenance.evidence_id:
                raise ValueError("public calculation canonical IDs must match")
            if calc.input_display_aliases != tuple(
                aliases[key] for key in calc.provenance.input_evidence_ids
            ):
                raise ValueError("public input aliases must resolve")
        return self


class PublicReportManifest(ReportManifest):
    projection_version: ProjectionVersion = "public-research-projection-v1"
    integrity_scope: IntegrityScope = "INTERNAL_RESEARCH_REPORT"
    file_hashes: None = None


class PublicEquityResearchReportResponse(CanonicalModel):
    report: PublicResearchReport
    markdown: str
    manifest_summary: PublicReportManifest


class PublicGroundedResearchAnswer(CanonicalModel):
    projection_version: ProjectionVersion = "public-research-projection-v1"
    ticker: Ticker
    as_of_date: Date
    plan: AgentPlan
    agent_status: AgentStatus
    used_skill_ids: Annotated[tuple[NonEmpty, ...], Field(min_length=1, max_length=1)]
    claims: tuple[GroundedClaim, ...]
    quality: QualityReport
    synthesis_readiness: SynthesisReadiness
    limitations: tuple[str, ...]
    unavailable_context: tuple[str, ...] = ()
    citations: dict[str, PublicEvidenceReference]
    calculation_provenance: tuple[PublicCalculationProvenance, ...]
    trace: AgentExecutionTrace
    llm_usage: tuple[LLMUsageMetadata, ...]
    planner_prompt_version: NonEmpty
    synthesis_prompt_version: NonEmpty
    synthesis_payload_audit: SynthesisPayloadAudit | None = None
    response_language: Literal[ResponseLanguage.ENGLISH, ResponseLanguage.CHINESE]
    language_fallback: bool = False
    rendered_answer: str

    @model_validator(mode="after")
    def public_integrity(self) -> "PublicGroundedResearchAnswer":
        if any(key != ref.evidence_id for key, ref in self.citations.items()):
            raise ValueError("public citation keys must match evidence IDs")
        if any(not set(claim.evidence_ids) <= self.citations.keys() for claim in self.claims):
            raise ValueError("public claim citations must resolve")
        _references_resolve(tuple(self.citations.values()), self.calculation_provenance)
        return self


class PublicToolResult(ToolResult):
    projection_version: ProjectionVersion = "public-research-projection-v1"
    evidence: tuple[PublicEvidenceReference, ...] = ()
    calculation_provenance: tuple[PublicCalculationProvenance, ...] = ()

    @model_validator(mode="after")
    def public_integrity(self) -> "PublicToolResult":
        _references_resolve(self.evidence, self.calculation_provenance)
        return self


class PublicCompanySnapshotResult(CompanySnapshotResult, PublicToolResult):
    evidence: tuple[PublicEvidenceReference, ...] = ()
    calculation_provenance: tuple[PublicCalculationProvenance, ...] = ()


class PublicMetricTrendResult(MetricTrendResult):
    evidence: tuple[PublicEvidenceReference, ...] = ()
    calculation_provenance: tuple[PublicCalculationProvenance, ...] = ()

    @model_validator(mode="after")
    def public_integrity(self) -> "PublicMetricTrendResult":
        _references_resolve(self.evidence, self.calculation_provenance)
        return self


class PublicFundamentalTrendResult(FundamentalTrendResult, PublicToolResult):
    evidence: tuple[PublicEvidenceReference, ...] = ()
    calculation_provenance: tuple[PublicCalculationProvenance, ...] = ()
    metrics: tuple[PublicMetricTrendResult, ...]


class PublicPeriodComparisonResult(PeriodComparisonResult, PublicToolResult):
    evidence: tuple[PublicEvidenceReference, ...] = ()
    calculation_provenance: tuple[PublicCalculationProvenance, ...] = ()
    result: PublicMetricTrendResult


class PublicMarketBehaviorResult(MarketBehaviorResult, PublicToolResult):
    evidence: tuple[PublicEvidenceReference, ...] = ()
    calculation_provenance: tuple[PublicCalculationProvenance, ...] = ()


class PublicResearchQualityResult(ResearchQualityResult, PublicToolResult):
    evidence: tuple[PublicEvidenceReference, ...] = ()
    calculation_provenance: tuple[PublicCalculationProvenance, ...] = ()
