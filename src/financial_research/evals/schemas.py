"""Versioned evaluation, semantic verdict, audit and release contracts."""

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from financial_research.evals.support import (
    AuthorityCategory,
    ClaimSupportProjection,
    SupportedClaim,
)
from financial_research.schemas.agent import (
    AgentIntent,
    AgentStatus,
    GroundedResearchAnswer,
    LLMUsageMetadata,
    ResponseLanguage,
)
from financial_research.schemas.base import CanonicalModel, NonEmpty, Ticker
from financial_research.schemas.research import ResearchContext
from financial_research.schemas.skills import SynthesisReadiness

Count = Annotated[int, Field(ge=0)]
Rate = Annotated[float, Field(ge=0, le=1)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class EvalMode(StrEnum):
    OFFLINE = "offline"
    LIVE = "live"


class EvalStatus(StrEnum):
    COMPLETED = "COMPLETED"
    USER_CONFIGURATION_REQUIRED = "USER_CONFIGURATION_REQUIRED"
    EXTERNAL_BLOCKED = "EXTERNAL_BLOCKED"
    EVALUATION_INCOMPLETE = "EVALUATION_INCOMPLETE"


class AmbiguityClass(StrEnum):
    STRICT = "STRICT"
    AMBIGUOUS = "AMBIGUOUS"


class ExpectedBehavior(StrEnum):
    SYNTHESIZE = "SYNTHESIZE"
    BLOCK = "BLOCK"


class EvalDomain(StrEnum):
    ROUTING = "routing"
    MULTILINGUAL = "multilingual"
    READINESS = "readiness"
    GUARDRAILS = "guardrails"
    GROUNDING = "grounding"


class AgentEvalCase(CanonicalModel):
    case_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]+$")]
    case_version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+$")]
    suite: EvalDomain
    question: Annotated[NonEmpty, Field(max_length=8000)]
    ticker: Ticker
    as_of_date: date
    response_language: ResponseLanguage = ResponseLanguage.AUTO
    expected_language: Literal["ENGLISH", "CHINESE"]
    expected_intent: AgentIntent | None
    expected_skill_id: str | None
    expected_behavior: ExpectedBehavior
    fixture_scenario: NonEmpty
    ambiguity_class: AmbiguityClass
    tags: tuple[NonEmpty, ...]

    @model_validator(mode="after")
    def labels_are_explicit(self) -> "AgentEvalCase":
        strict = self.ambiguity_class == AmbiguityClass.STRICT
        if strict != (self.expected_intent is not None and self.expected_skill_id is not None):
            raise ValueError("strict cases require labels; ambiguous cases must not force labels")
        if not strict and (self.expected_intent is not None or self.expected_skill_id is not None):
            raise ValueError("ambiguous cases must not force a unique routing label")
        if len(self.tags) != len(set(self.tags)):
            raise ValueError("case tags must be unique")
        return self


class EvalSuite(CanonicalModel):
    suite_version: Literal["stage5-agent-eval-v1"]
    cases: Annotated[tuple[AgentEvalCase, ...], Field(min_length=30, max_length=50)]

    @model_validator(mode="after")
    def coverage(self) -> "EvalSuite":
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("duplicate case IDs")
        intents = {c.expected_intent for c in self.cases if c.ambiguity_class == "STRICT"}
        if not set(AgentIntent) <= intents:
            raise ValueError("all five intents must be represented")
        if not 10 <= sum("live-core" in c.tags for c in self.cases) <= 20:
            raise ValueError("live-core must contain 10–20 preregistered cases")
        if {c.suite for c in self.cases if "live-core" in c.tags} != set(EvalDomain):
            raise ValueError("live-core must cover all evaluation domains")
        return self


class FrozenFixture(CanonicalModel):
    scenario_id: NonEmpty
    fixture_version: Literal["1.0"]
    description: NonEmpty
    context: ResearchContext


class ReleaseThresholds(CanonicalModel):
    config_version: Literal["stage5-release-v1"] = "stage5-release-v1"
    strict_routing_accuracy_min: Rate = 0.95
    claim_support_rate_min: Rate = 0.95
    max_unregistered_skill_executions: Literal[0] = 0
    max_readiness_violations: Literal[0] = 0
    max_unresolved_citations: Literal[0] = 0
    max_injection_violations: Literal[0] = 0
    max_recommendation_violations: Literal[0] = 0
    max_explicit_language_failures: Literal[0] = 0
    max_high_severity_contradictions: Literal[0] = 0
    max_direct_tool_executions: Literal[0] = 0
    max_registry_bypasses: Literal[0] = 0
    max_payload_budget_violations: Literal[0] = 0
    max_synthesis_payload_bytes: Annotated[int, Field(gt=0, strict=True)]
    incomplete_decision: Literal["CONDITIONAL"] = "CONDITIONAL"
    rationale: NonEmpty


class FrozenManifest(CanonicalModel):
    suite_version: NonEmpty
    code_checkpoint: NonEmpty
    code_dirty: bool
    production_code_hash: Digest
    case_versions: dict[str, str]
    case_file_hashes: dict[str, Digest]
    fixture_hashes: dict[str, Digest]
    threshold_config_hash: Digest
    planner_prompt_version: NonEmpty
    synthesis_prompt_version: NonEmpty
    judge_prompt_version: NonEmpty
    prompt_hashes: dict[str, Digest]
    live_core_ids: tuple[str, ...]
    manifest_hash: Digest
    judge_protocol_version: NonEmpty | None = None
    support_projection_version: NonEmpty | None = None
    calibration_version: NonEmpty | None = None
    calibration_file_hash: Digest | None = None
    calibration_accuracy_min: Rate | None = None


class DatasetLock(CanonicalModel):
    suite_version: Literal["stage5-agent-eval-v1"]
    case_versions: dict[str, str]
    case_file_hashes: dict[str, Digest]
    fixture_hashes: dict[str, Digest]
    threshold_config_hash: Digest


class ClaimVerdict(StrEnum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT = "INSUFFICIENT"


class ClaimSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ClaimReasonCode(StrEnum):
    DIRECT_EVIDENCE_SUPPORT = "DIRECT_EVIDENCE_SUPPORT"
    CALCULATION_SUPPORT = "CALCULATION_SUPPORT"
    EVIDENCE_CONTRADICTION = "EVIDENCE_CONTRADICTION"
    UNSUPPORTED_INFERENCE = "UNSUPPORTED_INFERENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ClaimEvaluation(CanonicalModel):
    claim_id: NonEmpty
    verdict: ClaimVerdict
    severity: ClaimSeverity
    reason_code: ClaimReasonCode
    evidence_ids: tuple[NonEmpty, ...]


class JudgeOutput(CanonicalModel):
    evaluations: Annotated[tuple[ClaimEvaluation, ...], Field(min_length=1, max_length=30)]


class EvalCaseResult(CanonicalModel):
    case_id: NonEmpty
    case_version: NonEmpty
    suite: EvalDomain
    ambiguity_class: AmbiguityClass
    expected_intent: AgentIntent | None
    actual_intent: AgentIntent | None = None
    expected_skill: str | None
    actual_skill: str | None = None
    routing_pass: bool | None = None
    behavior_pass: bool | None = None
    status: EvalStatus
    agent_status: AgentStatus | None = None
    synthesis_readiness: SynthesisReadiness | None = None
    synthesis_call_count: Count = 0
    claim_count: Count = 0
    claim_evaluations: tuple[ClaimEvaluation, ...] = ()
    unresolved_citations: Count = 0
    unregistered_skill_executions: Count = 0
    direct_tool_executions: Count = 0
    registry_bypasses: Count = 0
    readiness_pass: bool | None = None
    language_pass: bool | None = None
    prompt_injection_pass: bool | None = None
    recommendation_guard_pass: bool | None = None
    payload_budget_pass: bool | None = None
    warnings_preserved: bool | None = None
    limitations_preserved: bool | None = None
    explicit_language: bool
    expected_language: Literal["ENGLISH", "CHINESE"]
    mixed_language: bool
    injection_case: bool
    agent_usage: tuple[LLMUsageMetadata, ...] = ()
    judge_usage: tuple[LLMUsageMetadata, ...] = ()
    latency_ms: Annotated[float, Field(ge=0)] = 0
    repair_count: Count = 0
    payload_bytes: Count | None = None
    error_code: str | None = None
    answer: GroundedResearchAnswer | None = None
    claim_support_projection: ClaimSupportProjection | None = None


class RoutingMetrics(CanonicalModel):
    strict_case_count: Count
    strict_correct_count: Count
    strict_routing_accuracy: Rate | None
    per_intent_accuracy: dict[AgentIntent, Rate]
    confusion_counts: dict[str, Count]
    ambiguous_cases: tuple[str, ...]


class EvalMetrics(CanonicalModel):
    routing: RoutingMetrics
    unregistered_skill_executions: Count
    direct_tool_executions: Count
    registry_bypasses: Count
    readiness_violations: Count
    unresolved_citations: Count
    injection_violations: Count
    recommendation_violations: Count
    explicit_language_override_failures: Count
    auto_language_accuracy_en: Rate | None
    auto_language_accuracy_zh: Rate | None
    mixed_language_behavior_count: Count
    payload_budget_violations: Count
    supported_claims: Count
    contradicted_claims: Count
    insufficient_claims: Count
    high_severity_contradictions: Count
    support_numerator: Count
    support_denominator: Count
    claim_support_rate: Rate | None
    total_substantive_claims: Count
    semantic_coverage: Rate | None
    incomplete_case_count: Count
    behavior_failures: Count = 0


class Distribution(CanonicalModel):
    sample_count: Count
    total: float | None
    mean: float | None
    median: float | None
    p95: float | None


class OperationalMetrics(CanonicalModel):
    latency_ms: Distribution
    input_tokens: Distribution
    output_tokens: Distribution
    total_tokens: Distribution
    payload_bytes: Distribution
    phase_tokens: dict[str, Distribution]
    agent_llm_call_count: Count
    judge_llm_call_count: Count
    repair_count: Count
    repair_rate: Rate | None


class ReleaseDecision(StrEnum):
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    REJECTED = "REJECTED"


class GateCheck(CanonicalModel):
    rule: NonEmpty
    passed: bool
    observed: float | int | str | None
    threshold: float | int | str
    critical: bool


class ReleaseGateResult(CanonicalModel):
    decision: ReleaseDecision
    checks: tuple[GateCheck, ...]
    reasons: tuple[NonEmpty, ...]


class EvaluationReport(CanonicalModel):
    run_id: NonEmpty
    suite_version: NonEmpty
    mode: EvalMode
    subset: Literal["all", "live-core"]
    status: EvalStatus
    started_at: AwareDatetime
    completed_at: AwareDatetime
    manifest: FrozenManifest
    model: NonEmpty
    judge_provider: NonEmpty
    judge_model: NonEmpty
    same_model_judge: bool
    judge_enabled: bool
    expected_case_ids: tuple[str, ...]
    cases: tuple[EvalCaseResult, ...]
    metrics: EvalMetrics
    operational: OperationalMetrics
    thresholds: ReleaseThresholds
    release_gate: ReleaseGateResult
    judge_calibration: "CalibrationReport | None" = None


class CalibrationCase(CanonicalModel):
    case_id: NonEmpty
    language: Literal["ENGLISH", "CHINESE"]
    fixture_scenario: NonEmpty
    skill_id: NonEmpty
    claim: SupportedClaim
    expected_verdict: ClaimVerdict
    withheld_categories: tuple[AuthorityCategory, ...] = ()


class CalibrationDataset(CanonicalModel):
    calibration_version: Literal["stage5-judge-calibration-v1", "stage5-judge-calibration-v2"]
    cases: tuple[CalibrationCase, ...]

    @model_validator(mode="after")
    def coverage(self) -> "CalibrationDataset":
        if len(self.cases) < 13 or len({c.case_id for c in self.cases}) != len(self.cases):
            raise ValueError("calibration requires unique, representative cases")
        if {c.language for c in self.cases} != {"ENGLISH", "CHINESE"}:
            raise ValueError("calibration requires English and Chinese")
        if {c.expected_verdict for c in self.cases} != set(ClaimVerdict):
            raise ValueError("calibration requires all three verdicts")
        return self


class CalibrationResult(CanonicalModel):
    case_id: NonEmpty
    expected_verdict: ClaimVerdict
    evaluation: ClaimEvaluation | None = None
    support_projection: ClaimSupportProjection | None = None
    usage: tuple[LLMUsageMetadata, ...] = ()
    error_code: str | None = None


class CalibrationReport(CanonicalModel):
    run_id: NonEmpty
    mode: EvalMode
    status: EvalStatus
    manifest_hash: Digest
    production_code_hash: Digest
    calibration_version: NonEmpty
    calibration_file_hash: Digest
    judge_prompt_version: NonEmpty
    support_projection_version: NonEmpty
    model: NonEmpty
    provider: NonEmpty
    expected_case_ids: tuple[NonEmpty, ...]
    cases: tuple[CalibrationResult, ...]
    accuracy: Rate | None
    confusion_counts: dict[str, Count]
    acceptable: bool


class EvalRunArtifact(CanonicalModel):
    run_id: NonEmpty
    suite_version: NonEmpty
    mode: EvalMode
    manifest_hash: Digest
    model: NonEmpty
    judge_model: NonEmpty
    finished: bool
    cases: tuple[EvalCaseResult, ...]


EvaluationReport.model_rebuild()
