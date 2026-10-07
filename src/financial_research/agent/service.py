"""One validated plan, one registered Skill, readiness gate and bounded structured synthesis."""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from financial_research.agent.config import AgentRuntimeConfig
from financial_research.agent.errors import (
    AgentIntegrityError,
    AgentPlanValidationError,
    GroundingValidationError,
    PayloadBudgetExceeded,
)
from financial_research.agent.evidence_projection import project_evidence
from financial_research.agent.grounding import validate_final_answer, validate_grounding
from financial_research.agent.language import resolve_language, validate_response_language
from financial_research.agent.planner import (
    INTENT_REASONS,
    INTENT_SKILLS,
    capability_manifest,
    validate_plan,
)
from financial_research.agent.prompts import (
    PLANNER_PROMPT,
    PLANNER_PROMPT_VERSION,
    SYNTHESIS_PROMPT,
    SYNTHESIS_PROMPT_VERSION,
)
from financial_research.agent.rendering import render_answer
from financial_research.agent.synthesis_payload import synthesis_payload
from financial_research.exceptions import ProviderError, UnknownTickerError
from financial_research.llm.base import LLMClient, LLMRequest
from financial_research.llm.errors import (
    AgentConfigurationError,
    LLMProviderError,
    LLMStructuredOutputError,
)
from financial_research.schemas.agent import (
    AgentExecutionTrace,
    AgentPlan,
    AgentStatus,
    AgentTraceAction,
    AgentTraceStep,
    GroundedClaim,
    GroundedResearchAnswer,
    LLMPhase,
    LLMUsageMetadata,
    ResearchAgentRequest,
    SynthesisOutput,
    SynthesisPayloadAudit,
)
from financial_research.schemas.skills import (
    FundamentalAnalysisResult,
    ResearchEvidencePackage,
    SkillResult,
    SkillStatus,
    SynthesisReadiness,
)
from financial_research.schemas.tools import CalculationProvenance, EvidenceReference
from financial_research.skills.readiness import synthesis_readiness
from financial_research.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)
MAX_REPAIRS = 1
MAX_LLM_CALLS = 4


@dataclass
class _Execution:
    steps: list[AgentTraceStep] = field(default_factory=list)
    usage: list[LLMUsageMetadata] = field(default_factory=list)
    calls: int = 0

    def record(
        self,
        action: AgentTraceAction,
        target: str,
        status: str = "SUCCESS",
        *,
        duration_ms: float | None = None,
        error_code: str | None = None,
    ) -> None:
        self.steps.append(
            AgentTraceStep.model_validate(
                {
                    "sequence": len(self.steps) + 1,
                    "action": action,
                    "target": target,
                    "status": status,
                    "duration_ms": duration_ms,
                    "error_code": error_code,
                }
            )
        )

    def trace(self) -> AgentExecutionTrace:
        return AgentExecutionTrace(steps=tuple(self.steps))

    def record_usage(self, usage: LLMUsageMetadata) -> None:
        self.usage.append(usage)
        logger.info(
            "agent LLM provider=%s model=%s phase=%s prompt_version=%s latency_ms=%.3f "
            "input_tokens=%s output_tokens=%s total_tokens=%s repair_count=%d success=%s",
            usage.provider,
            usage.model,
            usage.phase,
            usage.prompt_version,
            usage.latency_ms,
            usage.input_tokens,
            usage.output_tokens,
            usage.total_tokens,
            usage.repair_count,
            usage.success,
        )


class ResearchAgent:
    def __init__(
        self, *, registry: SkillRegistry, llm: LLMClient, config: AgentRuntimeConfig | None = None
    ) -> None:
        self._registry = registry
        self._llm = llm
        self._config = config or AgentRuntimeConfig.from_env()

    @property
    def llm_provider(self) -> str:
        return self._llm.provider

    @property
    def llm_model(self) -> str:
        return self._llm.model

    def execute_validated_plan(
        self, request: ResearchAgentRequest, plan: AgentPlan
    ) -> GroundedResearchAnswer:
        """Validate an internally supplied plan and reuse the normal execution pipeline."""
        execution = _Execution()
        try:
            try:
                plan = AgentPlan.model_validate(plan.model_dump())
            except ValidationError:
                raise AgentPlanValidationError("INVALID_PLAN_SCHEMA") from None
            validate_plan(plan, request, self._registry)
            execution.record(AgentTraceAction.PLAN_VALIDATED, "deterministic-equity-report-plan-v1")
            return self._execute(
                request,
                plan,
                execution,
                planner_prompt_version="deterministic-equity-report-plan-v1",
            )
        except (AgentIntegrityError, LLMProviderError) as exc:
            exc.trace, exc.llm_usage = execution.trace(), tuple(execution.usage)
            logger.warning(
                "agent failure error_type=%s llm_calls=%d", type(exc).__name__, execution.calls
            )
            raise

    def run(self, request: ResearchAgentRequest) -> GroundedResearchAnswer:
        execution = _Execution()
        try:
            return self._run(request, execution)
        except (AgentIntegrityError, LLMProviderError) as exc:
            exc.trace, exc.llm_usage = execution.trace(), tuple(execution.usage)
            logger.warning(
                "agent failure error_type=%s llm_calls=%d", type(exc).__name__, execution.calls
            )
            raise

    def _structured[T: BaseModel](
        self,
        execution: _Execution,
        *,
        output_type: type[T],
        phase: LLMPhase,
        repair_phase: LLMPhase,
        system_prompt: str,
        prompt_version: str,
        payload: str,
        validate: Callable[[T], None],
        error_type: type[AgentIntegrityError],
        request_action: AgentTraceAction,
        validation_action: AgentTraceAction,
    ) -> T:
        error_code: str | None = None
        for attempt in range(MAX_REPAIRS + 1):
            if execution.calls >= MAX_LLM_CALLS:
                raise AgentIntegrityError("LLM_CALL_BOUND_EXCEEDED")
            call_phase = repair_phase if attempt else phase
            request = LLMRequest(
                phase=call_phase,
                prompt_version=prompt_version,
                system_prompt=system_prompt,
                user_payload=payload
                if error_code is None
                else json.dumps(
                    {"original_input": json.loads(payload), "validation_error_codes": [error_code]},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                repair_count=attempt,
            )
            if phase == LLMPhase.SYNTHESIS:
                actual_bytes = len(request.user_payload.encode("utf-8"))
                budget = self._config.max_synthesis_payload_bytes
                if actual_bytes > budget:
                    raise PayloadBudgetExceeded(actual_bytes=actual_bytes, budget_bytes=budget)
            execution.calls += 1
            execution.record(request_action, call_phase)
            started = time.perf_counter()
            usage: LLMUsageMetadata | None = None
            try:
                response = self._llm.generate(request, output_type)
                usage = response.usage
                output = output_type.model_validate_json(response.content)
                validate(output)
            except LLMStructuredOutputError as exc:
                usage = exc.usage
                error_code = "INVALID_STRUCTURED_OUTPUT"
            except (ValidationError, AgentPlanValidationError, GroundingValidationError) as exc:
                error_code = (
                    exc.code if isinstance(exc, AgentIntegrityError) else "INVALID_OUTPUT_SCHEMA"
                )
            except LLMProviderError as exc:
                usage = exc.usage or self._unknown_usage(request, started)
                execution.record_usage(usage.model_copy(update={"success": False}))
                execution.record(
                    validation_action, call_phase, "FAILED", error_code="LLM_PROVIDER_ERROR"
                )
                raise
            except Exception:
                execution.record_usage(self._unknown_usage(request, started))
                execution.record(
                    validation_action, call_phase, "FAILED", error_code="LLM_ADAPTER_FAILURE"
                )
                raise AgentIntegrityError("LLM_ADAPTER_FAILURE") from None
            else:
                execution.record_usage(usage.model_copy(update={"success": True}))
                execution.record(validation_action, call_phase)
                return output
            usage = usage or self._unknown_usage(request, started)
            execution.record_usage(usage.model_copy(update={"success": False}))
            execution.record(
                validation_action,
                call_phase,
                "REPAIR_REQUIRED" if attempt < MAX_REPAIRS else "FAILED",
                error_code=error_code,
            )
        raise error_type(error_code or "OUTPUT_VALIDATION_FAILED")

    def _unknown_usage(self, request: LLMRequest, started: float) -> LLMUsageMetadata:
        return LLMUsageMetadata(
            provider=self._llm.provider,
            model=self._llm.model,
            phase=request.phase,
            prompt_version=request.prompt_version,
            latency_ms=(time.perf_counter() - started) * 1000,
            repair_count=request.repair_count,
            success=False,
        )

    def _run(self, request: ResearchAgentRequest, execution: _Execution) -> GroundedResearchAnswer:
        payload = json.dumps(
            {
                "request": request.model_dump(mode="json", exclude={"response_language"}),
                "skill_manifest": [
                    entry.model_dump(mode="json") for entry in capability_manifest(self._registry)
                ],
                "intent_skill_mapping": INTENT_SKILLS,
                "intent_reason_mapping": INTENT_REASONS,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        plan = self._structured(
            execution,
            output_type=AgentPlan,
            phase=LLMPhase.PLANNING,
            repair_phase=LLMPhase.PLANNING_REPAIR,
            system_prompt=PLANNER_PROMPT,
            prompt_version=PLANNER_PROMPT_VERSION,
            payload=payload,
            validate=lambda result: validate_plan(result, request, self._registry),
            error_type=AgentPlanValidationError,
            request_action=AgentTraceAction.PLAN_REQUEST,
            validation_action=AgentTraceAction.PLAN_VALIDATED,
        )
        return self._execute(
            request, plan, execution, planner_prompt_version=PLANNER_PROMPT_VERSION
        )

    def _execute(
        self,
        request: ResearchAgentRequest,
        plan: AgentPlan,
        execution: _Execution,
        *,
        planner_prompt_version: str,
    ) -> GroundedResearchAnswer:
        started = time.perf_counter()
        try:
            result = self._registry.get(plan.selected_skill_id).run(
                ticker=request.ticker, as_of_date=request.as_of_date
            )
            result = type(result).model_validate(result.model_dump())
            if (result.metadata.skill_id, result.metadata.ticker, result.metadata.as_of_date) != (
                plan.selected_skill_id,
                request.ticker,
                request.as_of_date,
            ):
                raise AgentIntegrityError("SKILL_RESULT_IDENTITY_MISMATCH")
        except AgentIntegrityError:
            execution.record(AgentTraceAction.SKILL_EXECUTION, plan.selected_skill_id, "FAILED")
            raise
        except Exception:
            execution.record(AgentTraceAction.SKILL_EXECUTION, plan.selected_skill_id, "FAILED")
            raise AgentIntegrityError("SKILL_EXECUTION_FAILURE") from None
        execution.record(
            AgentTraceAction.SKILL_EXECUTION,
            plan.selected_skill_id,
            "FAILED" if result.metadata.status == SkillStatus.FAILED else "SUCCESS",
            duration_ms=(time.perf_counter() - started) * 1000,
            error_code=result.metadata.error.error_code if result.metadata.error else None,
        )
        self._check_skill_failure(result)
        readiness = synthesis_readiness(result)
        execution.record(
            AgentTraceAction.READINESS_GATE,
            readiness,
            "BLOCKED" if readiness == SynthesisReadiness.NOT_READY else "SUCCESS",
        )
        if result.metadata.quality is None:
            raise AgentIntegrityError("MISSING_AUTHORITATIVE_QUALITY")
        claims: tuple[GroundedClaim, ...] = ()
        citations: dict[str, EvidenceReference] = {}
        calculations: tuple[CalculationProvenance, ...] = ()
        unavailable: tuple[str, ...] = ()
        payload_audit: SynthesisPayloadAudit | None = None
        response_language, language_fallback = resolve_language(request)
        if readiness == SynthesisReadiness.NOT_READY:
            status = AgentStatus.BLOCKED
            missing_metrics = (
                result.fundamental_analysis.unavailable_metrics
                if isinstance(result, (FundamentalAnalysisResult, ResearchEvidencePackage))
                and result.fundamental_analysis is not None
                else ()
            )
            unavailable = tuple(
                sorted(
                    {
                        f"SKILL_STATUS:{result.metadata.status}",
                        *result.limitations,
                        *(f"UNAVAILABLE_METRIC:{metric}" for metric in missing_metrics),
                    }
                )
            )
        else:
            projection = project_evidence(result)
            execution.record(AgentTraceAction.EVIDENCE_PROJECTION, "projection-v1")
            payload, payload_audit = synthesis_payload(
                question=request.question,
                projection=projection,
                response_language=response_language,
            )

            def validate_synthesis(output: SynthesisOutput) -> None:
                validate_grounding(output, projection)
                validate_response_language(output, response_language)

            synthesis = self._structured(
                execution,
                output_type=SynthesisOutput,
                phase=LLMPhase.SYNTHESIS,
                repair_phase=LLMPhase.SYNTHESIS_REPAIR,
                system_prompt=SYNTHESIS_PROMPT,
                prompt_version=SYNTHESIS_PROMPT_VERSION,
                payload=payload,
                validate=validate_synthesis,
                error_type=GroundingValidationError,
                request_action=AgentTraceAction.SYNTHESIS_REQUEST,
                validation_action=AgentTraceAction.GROUNDING_VALIDATION,
            )
            claims, citations = synthesis.claims, projection.evidence_index
            calculations = projection.calculation_provenance
            status = (
                AgentStatus.COMPLETED_WITH_WARNINGS
                if readiness == SynthesisReadiness.READY_WITH_WARNINGS
                else AgentStatus.COMPLETED
            )
        answer = GroundedResearchAnswer(
            ticker=request.ticker,
            as_of_date=request.as_of_date,
            plan=plan,
            agent_status=status,
            used_skill_ids=(plan.selected_skill_id,),
            claims=claims,
            quality=result.metadata.quality,
            synthesis_readiness=readiness,
            limitations=tuple(sorted(set(result.limitations))),
            unavailable_context=unavailable,
            citations=citations,
            calculation_provenance=calculations,
            trace=execution.trace(),
            llm_usage=tuple(execution.usage),
            planner_prompt_version=planner_prompt_version,
            synthesis_prompt_version=SYNTHESIS_PROMPT_VERSION,
            synthesis_payload_audit=payload_audit,
            response_language=response_language,
            language_fallback=language_fallback,
        )
        if readiness != SynthesisReadiness.NOT_READY:
            validate_final_answer(answer, projection)
        rendered = render_answer(answer)
        execution.record(AgentTraceAction.RESPONSE_RENDERED, "renderer-v1")
        logger.info(
            "agent completed skill=%s status=%s llm_calls=%d",
            plan.selected_skill_id,
            status,
            execution.calls,
        )
        return GroundedResearchAnswer.model_validate(
            {**answer.model_dump(), "rendered_answer": rendered, "trace": execution.trace()}
        )

    @staticmethod
    def _check_skill_failure(result: SkillResult) -> None:
        if result.metadata.status != SkillStatus.FAILED:
            return
        code = result.metadata.error.error_code if result.metadata.error else "SKILL_FAILED"
        if code == "CRITICAL_QUALITY_FAILURE":
            return
        if code == "PROVIDER_ERROR":
            raise ProviderError("Research provider failed.")
        if code == "CONFIGURATION_ERROR":
            raise AgentConfigurationError("Research service configuration required.")
        if code == "UNKNOWN_TICKER":
            raise UnknownTickerError("The ticker could not be resolved.")
        raise AgentIntegrityError(code)
