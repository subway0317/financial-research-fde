"""Evaluate actual bounded Agent runs against frozen inputs; never retune the benchmark."""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

from financial_research.agent.config import AgentRuntimeConfig
from financial_research.agent.errors import AgentIntegrityError, PayloadBudgetExceeded
from financial_research.agent.evidence_projection import project_evidence
from financial_research.agent.language import language_matches
from financial_research.agent.service import ResearchAgent
from financial_research.evals.dataset import DEFAULT_ROOT, load_suite, verify_manifest
from financial_research.evals.fixtures import fixture_registry, load_fixtures
from financial_research.evals.guardrails import (
    ObservedRegistry,
    agent_dependency_violations,
    policy_passes,
)
from financial_research.evals.judge import ClaimSupportJudge, SemanticEvaluationError
from financial_research.evals.metrics import aggregate_metrics, operational_metrics
from financial_research.evals.release_gate import AgentReleaseGate
from financial_research.evals.schemas import (
    AgentEvalCase,
    CalibrationReport,
    ClaimEvaluation,
    EvalCaseResult,
    EvalMode,
    EvalStatus,
    EvaluationReport,
    FrozenFixture,
    FrozenManifest,
    ReleaseGateResult,
    ReleaseThresholds,
)
from financial_research.evals.support import ClaimSupportProjection, support_for_answer
from financial_research.llm.base import LLMClient, LLMRequest, LLMResponse
from financial_research.llm.errors import LLMProviderError
from financial_research.schemas.agent import (
    AgentPlan,
    GroundedResearchAnswer,
    LLMUsageMetadata,
    ResearchAgentRequest,
    ResponseLanguage,
)
from financial_research.skills.readiness import synthesis_readiness


class ObservedLLM:
    def __init__(self, client: LLMClient) -> None:
        self.client = client
        self.provider, self.model = client.provider, client.model
        self.requests: list[LLMRequest] = []
        self.plan: AgentPlan | None = None

    def generate(self, request: LLMRequest, output_type: type[BaseModel]) -> LLMResponse:
        self.requests.append(request)
        response = self.client.generate(request, output_type)
        if output_type is AgentPlan:
            try:
                self.plan = AgentPlan.model_validate_json(response.content)
            except ValidationError:
                pass
        return response


def evaluate_case(
    case: AgentEvalCase,
    fixture: FrozenFixture,
    client: LLMClient,
    judge: ClaimSupportJudge | None,
    config: AgentRuntimeConfig,
) -> EvalCaseResult:
    started = time.perf_counter()
    registry = ObservedRegistry(fixture_registry(fixture))
    observed = ObservedLLM(client)
    answer: GroundedResearchAnswer | None = None
    status, error_code = EvalStatus.COMPLETED, None
    agent_usage: tuple[LLMUsageMetadata, ...] = ()
    judge_usage: tuple[LLMUsageMetadata, ...] = ()
    evaluations: tuple[ClaimEvaluation, ...] = ()
    payload_bytes: int | None = None
    support: ClaimSupportProjection | None = None
    try:
        answer = ResearchAgent(registry=registry, llm=observed, config=config).run(
            ResearchAgentRequest(
                question=case.question,
                ticker=case.ticker,
                as_of_date=case.as_of_date,
                response_language=case.response_language,
            )
        )
        agent_usage = answer.llm_usage
        payload_bytes = (
            answer.synthesis_payload_audit.request_bytes if answer.synthesis_payload_audit else None
        )
        if judge is not None:
            try:
                if answer.claims:
                    if registry.result is None:
                        raise ValueError("authoritative Skill result missing")
                    support = support_for_answer(answer, project_evidence(registry.result))
                evaluations, judge_usage = judge.evaluate(answer, support)
            except SemanticEvaluationError as exc:
                status, error_code, judge_usage = (
                    EvalStatus.EVALUATION_INCOMPLETE,
                    exc.code,
                    exc.usage,
                )
    except LLMProviderError as exc:
        status, error_code, agent_usage = (
            EvalStatus.EXTERNAL_BLOCKED,
            "LLM_PROVIDER_ERROR",
            exc.llm_usage,
        )
    except AgentIntegrityError as exc:
        error_code, agent_usage = exc.code, exc.llm_usage
        if isinstance(exc, PayloadBudgetExceeded):
            payload_bytes = exc.actual_bytes
    except Exception:
        status, error_code = EvalStatus.EVALUATION_INCOMPLETE, "EVAL_RUNTIME_ERROR"
    synth_requests = [r for r in observed.requests if r.phase in {"SYNTHESIS", "SYNTHESIS_REPAIR"}]
    allowed = {definition.skill_id for definition in registry.list()}
    unregistered = sum(skill not in allowed for skill in registry.executions)
    bypasses = max(0, len(registry.executions) - 1) + sum(
        skill not in registry.lookups for skill in registry.executions
    )
    boundary = agent_dependency_violations()
    skill_result = registry.result
    readiness = synthesis_readiness(skill_result) if skill_result is not None else None
    readiness_pass = None
    if readiness is not None:
        readiness_pass = (
            (answer is not None and answer.agent_status == "BLOCKED" and not synth_requests)
            if readiness == "NOT_READY"
            else bool(synth_requests)
        )
    language_pass = None
    if answer is not None and answer.claims:
        language_pass = answer.response_language == case.expected_language and all(
            language_matches(c.statement, ResponseLanguage(case.expected_language))
            for c in answer.claims
        )
    elif error_code == "LANGUAGE_CONTRACT_VIOLATION":
        language_pass = False
    actual_skill = registry.executions[0] if registry.executions else None
    actual_intent = observed.plan.intent if observed.plan else None
    behavior_pass = answer is not None and (
        (case.expected_behavior == "BLOCK" and answer.agent_status == "BLOCKED")
        or (case.expected_behavior == "SYNTHESIZE" and bool(answer.claims))
    )
    unresolved = (
        sum(key not in answer.citations for claim in answer.claims for key in claim.evidence_ids)
        if answer
        else 0
    )
    payload_pass = all(
        len(r.user_payload.encode("utf-8")) <= config.max_synthesis_payload_bytes
        for r in synth_requests
    )
    if isinstance(error_code, str) and error_code == "SYNTHESIS_PAYLOAD_BUDGET_EXCEEDED":
        payload_pass = False  # Safe runtime stop, but this preregistered normal case did not fit.
    return EvalCaseResult(
        case_id=case.case_id,
        case_version=case.case_version,
        suite=case.suite,
        ambiguity_class=case.ambiguity_class,
        expected_intent=case.expected_intent,
        actual_intent=actual_intent,
        expected_skill=case.expected_skill_id,
        actual_skill=actual_skill,
        routing_pass=(
            actual_intent == case.expected_intent and actual_skill == case.expected_skill_id
        )
        if case.ambiguity_class == "STRICT" and status != "EXTERNAL_BLOCKED"
        else None,
        behavior_pass=behavior_pass if status != "EXTERNAL_BLOCKED" else None,
        status=status,
        agent_status=answer.agent_status if answer else None,
        synthesis_readiness=readiness,
        synthesis_call_count=len(synth_requests),
        claim_count=len(answer.claims) if answer else 0,
        claim_evaluations=evaluations,
        unresolved_citations=unresolved,
        unregistered_skill_executions=unregistered,
        direct_tool_executions=boundary,
        registry_bypasses=bypasses,
        readiness_pass=readiness_pass if status != "EXTERNAL_BLOCKED" else None,
        language_pass=language_pass,
        prompt_injection_pass=unregistered == 0 and boundary == 0 and bypasses == 0,
        recommendation_guard_pass=policy_passes(answer) if answer else None,
        payload_budget_pass=payload_pass,
        warnings_preserved=answer.quality == skill_result.metadata.quality
        if answer and skill_result
        else None,
        limitations_preserved=set(skill_result.limitations) <= set(answer.limitations)
        if answer and skill_result
        else None,
        explicit_language=case.response_language != "AUTO",
        expected_language=case.expected_language,
        mixed_language="mixed" in case.tags,
        injection_case="injection" in case.tags,
        agent_usage=agent_usage,
        judge_usage=judge_usage,
        latency_ms=(time.perf_counter() - started) * 1000,
        repair_count=sum(u.repair_count > 0 for u in agent_usage),
        payload_bytes=payload_bytes,
        error_code=error_code,
        answer=answer,
        claim_support_projection=support,
    )


def build_report(
    *,
    run_id: str,
    mode: EvalMode,
    subset: str,
    manifest: FrozenManifest,
    thresholds: ReleaseThresholds,
    expected_ids: tuple[str, ...],
    cases: tuple[EvalCaseResult, ...],
    model: str,
    judge_provider: str,
    judge_model: str,
    judge_enabled: bool,
    started_at: datetime,
    status: EvalStatus | None = None,
    judge_calibration: CalibrationReport | None = None,
) -> EvaluationReport:
    if status is None:
        status = (
            EvalStatus.EXTERNAL_BLOCKED
            if any(c.status == "EXTERNAL_BLOCKED" for c in cases)
            else EvalStatus.EVALUATION_INCOMPLETE
            if any(c.status != "COMPLETED" for c in cases)
            else EvalStatus.COMPLETED
        )
    report = EvaluationReport.model_validate(
        {
            "run_id": run_id,
            "suite_version": manifest.suite_version,
            "mode": mode,
            "subset": subset,
            "status": status,
            "started_at": started_at,
            "completed_at": datetime.now(UTC),
            "manifest": manifest,
            "model": model,
            "judge_provider": judge_provider,
            "judge_model": judge_model,
            "same_model_judge": judge_enabled and model != "unconfigured" and model == judge_model,
            "judge_enabled": judge_enabled,
            "expected_case_ids": expected_ids,
            "cases": cases,
            "judge_calibration": judge_calibration,
            "metrics": aggregate_metrics(cases),
            "operational": operational_metrics(cases),
            "thresholds": thresholds,
            "release_gate": ReleaseGateResult(
                decision="CONDITIONAL", checks=(), reasons=("pending",)
            ),
        }
    )
    return report.model_copy(update={"release_gate": AgentReleaseGate().evaluate(report)})


def run_suite(
    *,
    run_id: str,
    mode: EvalMode,
    subset: str,
    manifest: FrozenManifest,
    agent_client: Callable[[AgentEvalCase], LLMClient],
    judge_client: Callable[[], LLMClient] | None,
    model: str,
    judge_model: str,
    judge_provider: str,
    root: Path = DEFAULT_ROOT,
    progress: Callable[[tuple[EvalCaseResult, ...]], None] | None = None,
    judge_calibration: CalibrationReport | None = None,
) -> EvaluationReport:
    verify_manifest(manifest, root)
    if mode == EvalMode.LIVE and subset != "live-core":
        raise ValueError("live benchmark must use preregistered live-core")
    suite, thresholds = load_suite(root)
    fixtures = load_fixtures(root)
    selected = tuple(c for c in suite.cases if subset == "all" or "live-core" in c.tags)
    started_at = datetime.now(UTC)
    if mode == EvalMode.LIVE and judge_provider == "openai":
        from financial_research.evals.calibration import calibration_qualifies

        if not calibration_qualifies(judge_calibration, manifest, judge_model):
            return build_report(
                run_id=run_id,
                mode=mode,
                subset=subset,
                manifest=manifest,
                thresholds=thresholds,
                expected_ids=tuple(c.case_id for c in selected),
                cases=(),
                model=model,
                judge_provider=judge_provider,
                judge_model=judge_model,
                judge_enabled=judge_client is not None,
                started_at=started_at,
                status=EvalStatus.EVALUATION_INCOMPLETE,
                judge_calibration=judge_calibration,
            )
    results = []
    config = AgentRuntimeConfig(max_synthesis_payload_bytes=thresholds.max_synthesis_payload_bytes)
    protocol_changed = False
    for case in selected:
        try:
            verify_manifest(manifest, root)
        except ValueError:
            protocol_changed = True
            break
        judge = ClaimSupportJudge(judge_client()) if judge_client is not None else None
        result = evaluate_case(
            case, fixtures[case.fixture_scenario], agent_client(case), judge, config
        )
        results.append(result)
        if progress is not None:
            progress(tuple(results))
        if result.status == "EXTERNAL_BLOCKED" or result.error_code == "JUDGE_PROVIDER_ERROR":
            break  # Preserve partial baseline; no repeated quota/outage requests.
    try:
        verify_manifest(manifest, root)
    except ValueError:
        protocol_changed = True
    return build_report(
        run_id=run_id,
        mode=mode,
        subset=subset,
        manifest=manifest,
        thresholds=thresholds,
        expected_ids=tuple(c.case_id for c in selected),
        cases=tuple(results),
        model=model,
        judge_provider=judge_provider,
        judge_model=judge_model,
        judge_enabled=judge_client is not None,
        started_at=started_at,
        status=EvalStatus.EVALUATION_INCOMPLETE if protocol_changed else None,
        judge_calibration=judge_calibration,
    )
