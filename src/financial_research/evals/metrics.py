"""Deterministic denominators and standard-library operational distributions."""

import math
import statistics
from collections import Counter
from collections.abc import Sequence

from financial_research.evals.schemas import (
    ClaimSeverity,
    ClaimVerdict,
    Distribution,
    EvalCaseResult,
    EvalMetrics,
    OperationalMetrics,
    RoutingMetrics,
)
from financial_research.schemas.agent import AgentIntent


def distribution(values: Sequence[float | int]) -> Distribution:
    ordered = sorted(values)
    if not ordered:
        return Distribution(sample_count=0, total=None, mean=None, median=None, p95=None)
    return Distribution(
        sample_count=len(ordered),
        total=sum(ordered),
        mean=statistics.mean(ordered),
        median=statistics.median(ordered),
        p95=ordered[math.ceil(len(ordered) * 0.95) - 1],
    )


def _accuracy(values: Sequence[bool | None]) -> float | None:
    available = [value for value in values if value is not None]
    return sum(available) / len(available) if available else None


def aggregate_metrics(cases: tuple[EvalCaseResult, ...]) -> EvalMetrics:
    strict = tuple(case for case in cases if case.ambiguity_class == "STRICT")
    correct = sum(case.routing_pass is True for case in strict)
    per_intent = {}
    for intent in AgentIntent:
        rows = [case for case in strict if case.expected_intent == intent]
        if rows:
            per_intent[intent] = sum(case.routing_pass is True for case in rows) / len(rows)
    confusion = Counter(
        f"{case.expected_intent}->{case.actual_intent or 'UNAVAILABLE'}" for case in strict
    )
    evaluations = [evaluation for case in cases for evaluation in case.claim_evaluations]
    counts = Counter(evaluation.verdict for evaluation in evaluations)
    claim_count = sum(case.claim_count for case in cases)
    return EvalMetrics(
        routing=RoutingMetrics(
            strict_case_count=len(strict),
            strict_correct_count=correct,
            strict_routing_accuracy=correct / len(strict) if strict else None,
            per_intent_accuracy=per_intent,
            confusion_counts=dict(sorted(confusion.items())),
            ambiguous_cases=tuple(
                case.case_id for case in cases if case.ambiguity_class == "AMBIGUOUS"
            ),
        ),
        unregistered_skill_executions=sum(c.unregistered_skill_executions for c in cases),
        direct_tool_executions=sum(c.direct_tool_executions for c in cases),
        registry_bypasses=sum(c.registry_bypasses for c in cases),
        readiness_violations=sum(
            c.readiness_pass is False
            or c.warnings_preserved is False
            or c.limitations_preserved is False
            for c in cases
        ),
        unresolved_citations=sum(c.unresolved_citations for c in cases),
        injection_violations=sum(
            c.prompt_injection_pass is False for c in cases if c.injection_case
        ),
        recommendation_violations=sum(c.recommendation_guard_pass is False for c in cases),
        explicit_language_override_failures=sum(
            c.language_pass is False for c in cases if c.explicit_language
        ),
        auto_language_accuracy_en=_accuracy(
            [
                c.language_pass
                for c in cases
                if not c.explicit_language
                and c.expected_language == "ENGLISH"
                and not c.mixed_language
            ]
        ),
        auto_language_accuracy_zh=_accuracy(
            [
                c.language_pass
                for c in cases
                if not c.explicit_language
                and c.expected_language == "CHINESE"
                and not c.mixed_language
            ]
        ),
        mixed_language_behavior_count=sum(c.mixed_language for c in cases),
        payload_budget_violations=sum(c.payload_budget_pass is False for c in cases),
        supported_claims=counts[ClaimVerdict.SUPPORTED],
        contradicted_claims=counts[ClaimVerdict.CONTRADICTED],
        insufficient_claims=counts[ClaimVerdict.INSUFFICIENT],
        high_severity_contradictions=sum(
            e.verdict == ClaimVerdict.CONTRADICTED and e.severity == ClaimSeverity.HIGH
            for e in evaluations
        ),
        support_numerator=counts[ClaimVerdict.SUPPORTED],
        support_denominator=len(evaluations),
        claim_support_rate=counts[ClaimVerdict.SUPPORTED] / len(evaluations)
        if evaluations
        else None,
        total_substantive_claims=claim_count,
        semantic_coverage=len(evaluations) / claim_count if claim_count else None,
        incomplete_case_count=sum(c.status != "COMPLETED" for c in cases),
        behavior_failures=sum(c.behavior_pass is False for c in cases),
    )


def operational_metrics(cases: tuple[EvalCaseResult, ...]) -> OperationalMetrics:
    agent = [usage for case in cases for usage in case.agent_usage]
    judge = [usage for case in cases for usage in case.judge_usage]
    all_usage = [*agent, *judge]
    phase_tokens = {}
    for phase in sorted({usage.phase for usage in all_usage}):
        for field in ("input_tokens", "output_tokens", "total_tokens"):
            values = [
                value
                for usage in all_usage
                if usage.phase == phase and (value := getattr(usage, field)) is not None
            ]
            phase_tokens[f"{phase}.{field}"] = distribution(values)
    return OperationalMetrics(
        latency_ms=distribution([case.latency_ms for case in cases]),
        input_tokens=distribution(
            [u.input_tokens for u in all_usage if u.input_tokens is not None]
        ),
        output_tokens=distribution(
            [u.output_tokens for u in all_usage if u.output_tokens is not None]
        ),
        total_tokens=distribution(
            [u.total_tokens for u in all_usage if u.total_tokens is not None]
        ),
        payload_bytes=distribution([c.payload_bytes for c in cases if c.payload_bytes is not None]),
        phase_tokens=phase_tokens,
        agent_llm_call_count=len(agent),
        judge_llm_call_count=len(judge),
        repair_count=sum(c.repair_count for c in cases),
        repair_rate=sum(c.repair_count > 0 for c in cases) / len(cases) if cases else None,
    )
