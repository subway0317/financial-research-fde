"""Typed workflow contracts, referencing the existing Stage 2 evidence system."""

import json
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import UUID4, AwareDatetime, Field, FiniteFloat, model_validator

from financial_research.fundamentals.registry import MetricKind
from financial_research.schemas.base import CanonicalModel, NonEmpty, Ticker
from financial_research.schemas.company import CompanyProfile
from financial_research.schemas.fundamentals import FundamentalObservation
from financial_research.schemas.provenance import ProvenanceRecord
from financial_research.schemas.quality import QualityIssue, QualityReport, QualityStatus
from financial_research.schemas.tools import (
    CalculationProvenance,
    ComparisonType,
    EvidenceKind,
    EvidenceReference,
    LatestMarketFeatures,
    MarketWindowSummary,
    MetricSnapshot,
    PercentageChangeStatus,
    ResultStatus,
    TrendDirection,
)


class SkillStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


class SynthesisReadiness(StrEnum):
    READY = "READY"
    READY_WITH_WARNINGS = "READY_WITH_WARNINGS"
    NOT_READY = "NOT_READY"


class SkillDefinition(CanonicalModel):
    skill_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+(?:\.[0-9]+)?$")]
    name: NonEmpty
    description: NonEmpty
    required_tools: tuple[NonEmpty, ...]
    required_skills: tuple[NonEmpty, ...] = ()
    input_type: NonEmpty
    output_type: NonEmpty
    capabilities: tuple[NonEmpty, ...]

    @model_validator(mode="after")
    def unique_metadata(self) -> "SkillDefinition":
        for values in (self.required_tools, self.required_skills, self.capabilities):
            if len(set(values)) != len(values):
                raise ValueError("skill metadata entries must be unique")
        if not self.capabilities:
            raise ValueError("a skill must expose at least one capability")
        return self


class SkillInput(CanonicalModel):
    ticker: Ticker
    as_of_date: date


class FundamentalAnalysisInput(SkillInput):
    metrics: Annotated[list[NonEmpty], Field(min_length=1, max_length=10)] | None = None

    @model_validator(mode="after")
    def unique_metrics(self) -> "FundamentalAnalysisInput":
        if self.metrics is not None and len(set(self.metrics)) != len(self.metrics):
            raise ValueError("metrics must be unique")
        return self


class MarketAnalysisInput(SkillInput):
    lookback_sessions: Annotated[int, Field(ge=2, le=504, strict=True)] = 60


class EquityResearchInput(FundamentalAnalysisInput):
    lookback_sessions: Annotated[int, Field(ge=2, le=504, strict=True)] = 60


class SkillErrorMetadata(CanonicalModel):
    error_code: NonEmpty
    message: NonEmpty
    target: NonEmpty


class SkillResultMetadata(CanonicalModel):
    skill_id: NonEmpty
    skill_version: NonEmpty
    ticker: Ticker
    as_of_date: date
    execution_id: UUID4
    generated_at: AwareDatetime
    status: SkillStatus
    quality: QualityReport | None = None
    error: SkillErrorMetadata | None = None

    @model_validator(mode="after")
    def failure_is_explicit(self) -> "SkillResultMetadata":
        if self.error is not None and self.status != SkillStatus.FAILED:
            raise ValueError("execution errors require FAILED")
        if self.quality is not None and self.quality.status == QualityStatus.FAIL:
            if self.status != SkillStatus.FAILED:
                raise ValueError("quality FAIL requires skill FAILED")
        return self


class TraceAction(StrEnum):
    CONTEXT_BUILD = "CONTEXT_BUILD"
    CONTEXT_REUSE = "CONTEXT_REUSE"
    QUALITY_GATE = "QUALITY_GATE"
    TOOL_CALL = "TOOL_CALL"
    TOOL_REUSE = "TOOL_REUSE"
    SKILL_CALL = "SKILL_CALL"
    EVIDENCE_MERGE = "EVIDENCE_MERGE"
    PACKAGE_ASSEMBLY = "PACKAGE_ASSEMBLY"


class SkillTraceStep(CanonicalModel):
    sequence: Annotated[int, Field(ge=1, strict=True)]
    action_type: TraceAction
    target: NonEmpty
    status: SkillStatus
    quality_status: QualityStatus | None = None
    error_code: str | None = None
    duration_ms: Annotated[FiniteFloat, Field(ge=0)] | None = None


class SkillExecutionTrace(CanonicalModel):
    steps: tuple[SkillTraceStep, ...] = ()

    @model_validator(mode="after")
    def sequential_actions(self) -> "SkillExecutionTrace":
        if [step.sequence for step in self.steps] != list(range(1, len(self.steps) + 1)):
            raise ValueError("trace sequence must be contiguous and ordered")
        return self


class CompanyOverviewSection(CanonicalModel):
    company: CompanyProfile
    latest_market_session: date | None
    latest_close: FiniteFloat | None
    market_windows: tuple[MarketWindowSummary, ...]
    latest_market_features: LatestMarketFeatures
    fundamentals: tuple[MetricSnapshot, ...]
    evidence_ids: tuple[NonEmpty, ...]


class MetricAnalysis(CanonicalModel):
    metric: NonEmpty
    metric_kind: MetricKind
    current_observation: FundamentalObservation | None = None
    comparable_observation: FundamentalObservation | None = None
    comparison_type: ComparisonType
    comparison_status: ResultStatus
    absolute_change: Annotated[Decimal, Field(allow_inf_nan=False)] | None = None
    percentage_change: Annotated[Decimal, Field(allow_inf_nan=False)] | None = None
    percentage_change_status: PercentageChangeStatus
    direction: TrendDirection
    evidence_ids: tuple[NonEmpty, ...]
    calculation_ids: tuple[NonEmpty, ...]
    limitations: tuple[NonEmpty, ...]


class FundamentalAnalysisSection(CanonicalModel):
    metrics: tuple[MetricAnalysis, ...]
    available_metrics: tuple[str, ...]
    unavailable_metrics: tuple[str, ...]
    evidence_ids: tuple[NonEmpty, ...]


class MarketAnalysisSection(CanonicalModel):
    latest_market_session: date | None
    latest_close: FiniteFloat | None
    window: MarketWindowSummary
    latest_market_features: LatestMarketFeatures
    evidence_ids: tuple[NonEmpty, ...]
    descriptive_only: Literal[True] = True


class ResearchQualitySection(CanonicalModel):
    overall_status: QualityStatus
    issues: tuple[QualityIssue, ...]
    critical_issues: tuple[QualityIssue, ...]
    warnings: tuple[QualityIssue, ...]
    latest_market_session: date | None
    market_age_calendar_days: int | None
    latest_fundamental_available_date: date | None
    fundamental_age_calendar_days: int | None
    available_registered_metrics: tuple[str, ...]
    missing_registered_metrics: tuple[str, ...]
    provenance_summary: tuple[ProvenanceRecord, ...]
    evidence_ids: tuple[NonEmpty, ...]


class SkillResult(CanonicalModel):
    schema_version: Literal["1.0"] = "1.0"
    metadata: SkillResultMetadata
    evidence_index: dict[str, EvidenceReference] = Field(default_factory=dict)
    calculation_provenance: tuple[CalculationProvenance, ...] = ()
    limitations: tuple[NonEmpty, ...] = ()
    execution_trace: SkillExecutionTrace

    @model_validator(mode="after")
    def grounded_calculations(self) -> "SkillResult":
        for key, reference in self.evidence_index.items():
            if key != reference.evidence_id:
                raise ValueError("evidence index key does not match reference")
        calculation_ids = {calc.evidence_id for calc in self.calculation_provenance}
        if len(calculation_ids) != len(self.calculation_provenance):
            raise ValueError("calculation provenance must be unique")
        computed_ids = {
            key for key, ref in self.evidence_index.items() if ref.kind == EvidenceKind.COMPUTATION
        }
        if calculation_ids != computed_ids:
            raise ValueError("every computation requires exactly one provenance record")
        for calc in self.calculation_provenance:
            if (
                not calc.input_evidence_ids
                or not set(calc.input_evidence_ids) <= self.evidence_index.keys()
            ):
                raise ValueError("calculation inputs must resolve in the evidence index")
        return self

    def normalized_business_json(self) -> str:
        def normalize(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: normalize(item)
                    for key, item in value.items()
                    if key
                    not in {
                        "execution_id",
                        "generated_at",
                        "retrieved_at",
                        "request_id",
                        "duration_ms",
                        "started_at",
                        "completed_at",
                    }
                }
            if isinstance(value, list):
                return [normalize(item) for item in value]
            return value

        return json.dumps(
            normalize(self.model_dump(mode="json")), sort_keys=True, separators=(",", ":")
        )


class CompanyOverviewResult(SkillResult):
    company_overview: CompanyOverviewSection | None = None


class FundamentalAnalysisResult(SkillResult):
    fundamental_analysis: FundamentalAnalysisSection | None = None


class MarketAnalysisResult(SkillResult):
    market_analysis: MarketAnalysisSection | None = None


class ResearchQualityAuditResult(SkillResult):
    research_quality: ResearchQualitySection | None = None


class ResearchEvidencePackage(SkillResult):
    synthesis_readiness: SynthesisReadiness = SynthesisReadiness.NOT_READY
    company_overview: CompanyOverviewSection | None = None
    fundamental_analysis: FundamentalAnalysisSection | None = None
    market_analysis: MarketAnalysisSection | None = None
    research_quality: ResearchQualitySection | None = None
    subskill_metadata: tuple[SkillResultMetadata, ...] = ()

    @model_validator(mode="after")
    def references_and_readiness(self) -> "ResearchEvidencePackage":
        ids = set(self.evidence_index)
        for section in (
            self.company_overview,
            self.fundamental_analysis,
            self.market_analysis,
            self.research_quality,
        ):
            if section is not None and not set(section.evidence_ids) <= ids:
                raise ValueError("section evidence IDs must resolve")
        if self.fundamental_analysis is not None:
            calculations = {calc.evidence_id for calc in self.calculation_provenance}
            for metric in self.fundamental_analysis.metrics:
                if (
                    not set(metric.evidence_ids) <= ids
                    or not set(metric.calculation_ids) <= calculations
                ):
                    raise ValueError("metric evidence and calculations must resolve")
        if self.metadata.status in {SkillStatus.FAILED, SkillStatus.UNAVAILABLE}:
            if self.synthesis_readiness != SynthesisReadiness.NOT_READY:
                raise ValueError("FAILED/UNAVAILABLE cannot be synthesis ready")
        if self.synthesis_readiness != SynthesisReadiness.NOT_READY and any(
            section is None
            for section in (
                self.company_overview,
                self.fundamental_analysis,
                self.market_analysis,
                self.research_quality,
            )
        ):
            raise ValueError("ready packages require every core section")
        if self.synthesis_readiness != SynthesisReadiness.NOT_READY:
            if self.metadata.quality is None:
                raise ValueError("readiness requires authoritative quality")
            if self.company_overview is not None and (
                self.company_overview.latest_close is None
                or self.company_overview.latest_market_session is None
            ):
                raise ValueError("readiness requires current market state")
            if (
                self.fundamental_analysis is not None
                and not self.fundamental_analysis.available_metrics
            ):
                raise ValueError("readiness requires at least one legal fundamental comparison")
            if (
                self.market_analysis is not None
                and self.market_analysis.window.status != ResultStatus.AVAILABLE
            ):
                raise ValueError("readiness requires a complete requested market window")
        if self.synthesis_readiness == SynthesisReadiness.READY and (
            self.metadata.status != SkillStatus.SUCCESS
            or self.metadata.quality is None
            or self.metadata.quality.status != QualityStatus.PASS
            or self.limitations
        ):
            raise ValueError("READY requires successful, clean and sufficient evidence")
        for metadata in self.subskill_metadata:
            if (metadata.ticker, metadata.as_of_date, metadata.execution_id) != (
                self.metadata.ticker,
                self.metadata.as_of_date,
                self.metadata.execution_id,
            ):
                raise ValueError("subskills must share the same execution identity")
            if metadata.status == SkillStatus.FAILED and self.metadata.status != SkillStatus.FAILED:
                raise ValueError("subskill failure cannot be hidden")
        return self
