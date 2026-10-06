"""Transport-independent Stage 4 contracts; LLM outputs contain no reasoning fields."""

import json
from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, model_validator

from financial_research.schemas.base import CanonicalModel, NonEmpty, Ticker
from financial_research.schemas.quality import QualityReport, QualityStatus, Severity
from financial_research.schemas.skills import SkillStatus, SynthesisReadiness
from financial_research.schemas.tools import (
    CalculationProvenance,
    EvidenceReference,
    MarketWindowSummary,
)


class ResearchAgentRequest(CanonicalModel):
    question: Annotated[NonEmpty, Field(max_length=8000)]
    ticker: Ticker
    as_of_date: date


class AgentIntent(StrEnum):
    COMPANY_OVERVIEW = "COMPANY_OVERVIEW"
    FUNDAMENTAL_FOCUS = "FUNDAMENTAL_FOCUS"
    MARKET_FOCUS = "MARKET_FOCUS"
    QUALITY_FOCUS = "QUALITY_FOCUS"
    BROAD_RESEARCH = "BROAD_RESEARCH"


class AgentReasonCode(StrEnum):
    COMPANY_INFORMATION_REQUEST = "COMPANY_INFORMATION_REQUEST"
    FUNDAMENTAL_ANALYSIS_REQUEST = "FUNDAMENTAL_ANALYSIS_REQUEST"
    MARKET_ANALYSIS_REQUEST = "MARKET_ANALYSIS_REQUEST"
    DATA_QUALITY_REQUEST = "DATA_QUALITY_REQUEST"
    BROAD_EQUITY_RESEARCH_REQUEST = "BROAD_EQUITY_RESEARCH_REQUEST"


class ClaimSection(StrEnum):
    COMPANY = "COMPANY"
    FUNDAMENTALS = "FUNDAMENTALS"
    MARKET = "MARKET"
    QUALITY = "QUALITY"


class AgentPlan(CanonicalModel):
    plan_version: Literal["1.0"]
    intent: AgentIntent
    selected_skill_id: NonEmpty
    reason_code: AgentReasonCode
    ticker: Ticker
    as_of_date: date
    requested_focus: tuple[ClaimSection, ...] | None


class SkillCapability(CanonicalModel):
    skill_id: NonEmpty
    name: NonEmpty
    description: NonEmpty
    capabilities: tuple[NonEmpty, ...]
    input_type: NonEmpty
    required_inputs: tuple[Literal["ticker", "as_of_date"], ...] = ("ticker", "as_of_date")


class AgentStatus(StrEnum):
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class ClaimType(StrEnum):
    SOURCE_FACT = "SOURCE_FACT"
    COMPUTED_FACT = "COMPUTED_FACT"
    INTERPRETATION = "INTERPRETATION"


class GroundedClaim(CanonicalModel):
    claim_id: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")]
    section: ClaimSection
    claim_type: ClaimType
    statement: Annotated[NonEmpty, Field(max_length=2000)]
    evidence_ids: Annotated[tuple[NonEmpty, ...], Field(min_length=1, max_length=30)]


class SynthesisOutput(CanonicalModel):
    claims: Annotated[tuple[GroundedClaim, ...], Field(min_length=1, max_length=30)]
    used_skill_ids: Annotated[tuple[NonEmpty, ...], Field(min_length=1, max_length=1)]


class ProjectedFinding(CanonicalModel):
    section: ClaimSection
    metric: NonEmpty
    status: NonEmpty
    direction: str | None = None
    percentage_change_status: str | None = None
    evidence_ids: tuple[NonEmpty, ...]
    calculation_ids: tuple[NonEmpty, ...] = ()
    limitations: tuple[str, ...] = ()


class EvidenceProjection(CanonicalModel):
    projection_version: Literal["1.0"] = "1.0"
    ticker: Ticker
    as_of_date: date
    skill_id: NonEmpty
    skill_status: SkillStatus
    synthesis_readiness: SynthesisReadiness
    quality: QualityReport
    company_name: str | None
    market_windows: tuple[MarketWindowSummary, ...]
    findings: tuple[ProjectedFinding, ...]
    evidence_index: dict[str, EvidenceReference]
    calculation_provenance: tuple[CalculationProvenance, ...]
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def reference_integrity(self) -> "EvidenceProjection":
        ids = set(self.evidence_index)
        calc_ids = {calc.evidence_id for calc in self.calculation_provenance}
        if any(key != ref.evidence_id for key, ref in self.evidence_index.items()):
            raise ValueError("projection evidence keys must match IDs")
        for finding in self.findings:
            if not set(finding.evidence_ids) <= ids or not set(finding.calculation_ids) <= calc_ids:
                raise ValueError("projection finding references must resolve")
        for calc in self.calculation_provenance:
            if calc.evidence_id not in ids or not set(calc.input_evidence_ids) <= ids:
                raise ValueError("projection calculation references must resolve")
        return self


class QualityOccurrence(CanonicalModel):
    affected_date: date | None
    affected_context: str | None
    count: Annotated[int, Field(ge=1)]


class QualityIssueGroup(CanonicalModel):
    code: NonEmpty
    severity: Severity
    message: NonEmpty
    affected_field: str | None
    count: Annotated[int, Field(ge=1)]
    first_affected_date: date | None
    last_affected_date: date | None
    selected_evidence_occurrences: tuple[QualityOccurrence, ...]


class SynthesisQualitySummary(CanonicalModel):
    status: QualityStatus
    issue_count: Annotated[int, Field(ge=0)]
    groups: tuple[QualityIssueGroup, ...]

    @model_validator(mode="after")
    def authoritative_status_and_counts(self) -> "SynthesisQualitySummary":
        if sum(group.count for group in self.groups) != self.issue_count:
            raise ValueError("quality group counts must account for all diagnostics")
        severities = {group.severity for group in self.groups}
        expected = (
            QualityStatus.FAIL
            if Severity.ERROR in severities
            else QualityStatus.PASS_WITH_WARNINGS
            if Severity.WARNING in severities
            else QualityStatus.PASS
        )
        if self.status != expected:
            raise ValueError("quality summary must preserve authoritative status")
        return self


class SynthesisEvidenceDefinition(EvidenceReference):
    # Dictionary key already carries the immutable canonical ID.
    evidence_id: NonEmpty = Field(exclude=True)


class SynthesisCalculation(CalculationProvenance):
    evidence_id: NonEmpty = Field(exclude=True)


class SynthesisFinding(ProjectedFinding):
    # Computations are discoverable by evidence kind and matching provenance keys.
    calculation_ids: tuple[NonEmpty, ...] = Field(default=(), exclude=True)


class SynthesisProjection(CanonicalModel):
    """Compact LLM representation; canonical projection remains the grounding source."""

    projection_version: Literal["2.0"] = "2.0"
    ticker: Ticker
    as_of_date: date
    skill_id: NonEmpty
    skill_status: SkillStatus
    synthesis_readiness: SynthesisReadiness
    quality: SynthesisQualitySummary
    company_name: str | None
    market_windows: tuple[MarketWindowSummary, ...]
    findings: tuple[SynthesisFinding, ...]
    evidence_index: dict[str, SynthesisEvidenceDefinition]
    calculation_provenance: dict[str, SynthesisCalculation]
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def references_resolve(self) -> "SynthesisProjection":
        ids = set(self.evidence_index)
        if any(key != ref.evidence_id for key, ref in self.evidence_index.items()):
            raise ValueError("synthesis evidence keys must preserve canonical IDs")
        for finding in self.findings:
            if not set(finding.evidence_ids) <= ids:
                raise ValueError("synthesis finding references must resolve")
        for key, calc in self.calculation_provenance.items():
            if key != calc.evidence_id or key not in ids or not set(calc.input_evidence_ids) <= ids:
                raise ValueError("synthesis calculation references must resolve")
        return self


class SynthesisPayloadComponents(CanonicalModel):
    request_metadata_bytes: int
    findings_bytes: int
    evidence_definitions_bytes: int
    calculation_provenance_bytes: int
    quality_bytes: int
    limitations_bytes: int


class SynthesisPayloadAudit(CanonicalModel):
    """Only byte counts and object counts; never serialized inputs or provider data."""

    baseline_request_bytes: int
    request_bytes: int
    baseline_quality_bytes: int
    instruction_bytes: int
    output_schema_bytes: int
    components: SynthesisPayloadComponents
    evidence_count: int
    calculation_count: int
    quality_issue_count: int
    quality_group_count: int


class LLMPhase(StrEnum):
    PLANNING = "PLANNING"
    PLANNING_REPAIR = "PLANNING_REPAIR"
    SYNTHESIS = "SYNTHESIS"
    SYNTHESIS_REPAIR = "SYNTHESIS_REPAIR"


class LLMUsageMetadata(CanonicalModel):
    provider: NonEmpty
    model: NonEmpty
    phase: LLMPhase
    prompt_version: NonEmpty
    latency_ms: Annotated[FiniteFloat, Field(ge=0)]
    input_tokens: Annotated[int, Field(ge=0)] | None = None
    output_tokens: Annotated[int, Field(ge=0)] | None = None
    total_tokens: Annotated[int, Field(ge=0)] | None = None
    repair_count: Annotated[int, Field(ge=0, le=1)]
    success: bool


class AgentTraceAction(StrEnum):
    PLAN_REQUEST = "PLAN_REQUEST"
    PLAN_VALIDATED = "PLAN_VALIDATED"
    SKILL_EXECUTION = "SKILL_EXECUTION"
    READINESS_GATE = "READINESS_GATE"
    EVIDENCE_PROJECTION = "EVIDENCE_PROJECTION"
    SYNTHESIS_REQUEST = "SYNTHESIS_REQUEST"
    GROUNDING_VALIDATION = "GROUNDING_VALIDATION"
    RESPONSE_RENDERED = "RESPONSE_RENDERED"


class AgentTraceStep(CanonicalModel):
    sequence: Annotated[int, Field(ge=1)]
    action: AgentTraceAction
    target: NonEmpty
    status: Literal["SUCCESS", "REPAIR_REQUIRED", "BLOCKED", "FAILED"]
    duration_ms: Annotated[FiniteFloat, Field(ge=0)] | None = None
    error_code: str | None = None


class AgentExecutionTrace(CanonicalModel):
    steps: tuple[AgentTraceStep, ...]

    @model_validator(mode="after")
    def ordered(self) -> "AgentExecutionTrace":
        if [step.sequence for step in self.steps] != list(range(1, len(self.steps) + 1)):
            raise ValueError("trace sequence must be contiguous")
        return self


class GroundedResearchAnswer(CanonicalModel):
    ticker: Ticker
    as_of_date: date
    plan: AgentPlan
    agent_status: AgentStatus
    used_skill_ids: Annotated[tuple[NonEmpty, ...], Field(min_length=1, max_length=1)]
    claims: tuple[GroundedClaim, ...]
    quality: QualityReport
    synthesis_readiness: SynthesisReadiness
    limitations: tuple[str, ...]
    unavailable_context: tuple[str, ...] = ()
    citations: dict[str, EvidenceReference]
    calculation_provenance: tuple[CalculationProvenance, ...]
    trace: AgentExecutionTrace
    llm_usage: tuple[LLMUsageMetadata, ...]
    planner_prompt_version: NonEmpty
    synthesis_prompt_version: NonEmpty
    synthesis_payload_audit: SynthesisPayloadAudit | None = None
    rendered_answer: str = ""

    def normalized_business_json(self) -> str:
        def normalize(value: object) -> object:
            if isinstance(value, dict):
                return {
                    key: normalize(item)
                    for key, item in value.items()
                    if key not in {"duration_ms", "latency_ms"}
                }
            if isinstance(value, list):
                return [normalize(item) for item in value]
            return value

        return json.dumps(
            normalize(self.model_dump(mode="json")), sort_keys=True, separators=(",", ":")
        )

    @model_validator(mode="after")
    def answer_integrity(self) -> "GroundedResearchAnswer":
        if self.used_skill_ids != (self.plan.selected_skill_id,):
            raise ValueError("answer skill must match plan")
        if (self.ticker, self.as_of_date) != (self.plan.ticker, self.plan.as_of_date):
            raise ValueError("answer identity must match plan")
        if self.synthesis_readiness == SynthesisReadiness.NOT_READY:
            if self.agent_status != AgentStatus.BLOCKED or self.claims:
                raise ValueError("NOT_READY requires BLOCKED without claims")
        elif not self.claims or self.agent_status not in {
            AgentStatus.COMPLETED,
            AgentStatus.COMPLETED_WITH_WARNINGS,
        }:
            raise ValueError("ready answers require completed grounded claims")
        if len({claim.claim_id for claim in self.claims}) != len(self.claims):
            raise ValueError("claim IDs must be unique")
        if any(not set(claim.evidence_ids) <= self.citations.keys() for claim in self.claims):
            raise ValueError("claim citations must resolve")
        if len(self.llm_usage) > 4:
            raise ValueError("at most four LLM calls are allowed")
        return self
