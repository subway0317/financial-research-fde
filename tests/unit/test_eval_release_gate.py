from datetime import UTC, datetime

import pytest

from financial_research.evals.calibration import run_calibration
from financial_research.evals.dataset import freeze_manifest, load_suite
from financial_research.evals.metrics import aggregate_metrics, distribution, operational_metrics
from financial_research.evals.release_gate import AgentReleaseGate
from financial_research.evals.schemas import (
    ClaimEvaluation,
    EvalCaseResult,
    EvalMode,
    EvaluationReport,
    ReleaseGateResult,
)


def qualified_calibration(manifest, model):
    """Simulate recorded live metadata solely to exercise deterministic gate rules."""
    offline = run_calibration(
        run_id="gate-fixture", mode=EvalMode.OFFLINE, manifest=freeze_manifest(), model="scripted"
    )
    rows = tuple(
        row.model_copy(
            update={
                "usage": tuple(
                    u.model_copy(update={"provider": "openai", "model": model}) for u in row.usage
                )
            }
        )
        for row in offline.cases
    )
    return offline.model_copy(
        update={"mode": EvalMode.LIVE, "provider": "openai", "model": model, "cases": rows}
    )


def report():
    suite, thresholds = load_suite()
    cases = tuple(
        EvalCaseResult(
            case_id=f"test-{i}",
            case_version="1.0",
            suite="routing",
            ambiguity_class="STRICT",
            expected_intent="FUNDAMENTAL_FOCUS",
            actual_intent="FUNDAMENTAL_FOCUS",
            expected_skill="fundamental_analysis",
            actual_skill="fundamental_analysis",
            routing_pass=True,
            status="COMPLETED",
            claim_count=1,
            claim_evaluations=(
                ClaimEvaluation(
                    claim_id="c1",
                    verdict="SUPPORTED",
                    severity="LOW",
                    reason_code="DIRECT_EVIDENCE_SUPPORT",
                    evidence_ids=("e1",),
                ),
            ),
            readiness_pass=True,
            language_pass=True,
            prompt_injection_pass=True,
            recommendation_guard_pass=True,
            payload_budget_pass=True,
            warnings_preserved=True,
            limitations_preserved=True,
            explicit_language=True,
            expected_language="ENGLISH",
            mixed_language=False,
            injection_case=True,
        )
        for i in range(20)
    )
    manifest = freeze_manifest().model_copy(
        update={
            "live_core_ids": tuple(c.case_id for c in cases),
            "case_versions": {c.case_id: c.case_version for c in cases},
        }
    )
    return EvaluationReport(
        run_id="test-run",
        suite_version=suite.suite_version,
        mode="live",
        subset="live-core",
        status="COMPLETED",
        started_at=datetime(2025, 1, 1, tzinfo=UTC),
        completed_at=datetime(2025, 1, 1, tzinfo=UTC),
        manifest=manifest,
        model="fixture-model",
        judge_provider="fake",
        judge_model="fixture-judge",
        same_model_judge=False,
        judge_enabled=True,
        judge_calibration=qualified_calibration(manifest, "fixture-judge"),
        expected_case_ids=tuple(c.case_id for c in cases),
        cases=cases,
        metrics=aggregate_metrics(cases),
        operational=operational_metrics(cases),
        thresholds=thresholds,
        release_gate=ReleaseGateResult(decision="CONDITIONAL", checks=(), reasons=("pending",)),
    )


def test_exact_95_percent_routing_and_support_boundaries():
    baseline = report()
    assert AgentReleaseGate().evaluate(baseline).decision == "APPROVED"
    rows = list(baseline.cases)
    first = rows[0]
    insufficient = first.claim_evaluations[0].model_copy(update={"verdict": "INSUFFICIENT"})
    rows[0] = first.model_copy(update={"routing_pass": False, "claim_evaluations": (insufficient,)})
    candidate = baseline.model_copy(
        update={"cases": tuple(rows), "metrics": aggregate_metrics(tuple(rows))}
    )
    assert candidate.metrics.routing.strict_routing_accuracy == 0.95
    assert candidate.metrics.claim_support_rate == 0.95
    assert AgentReleaseGate().evaluate(candidate).decision == "APPROVED"
    rows[1] = rows[1].model_copy(update={"routing_pass": False})
    candidate = candidate.model_copy(
        update={"cases": tuple(rows), "metrics": aggregate_metrics(tuple(rows))}
    )
    assert AgentReleaseGate().evaluate(candidate).decision == "CONDITIONAL"


@pytest.mark.parametrize(
    "metric",
    [
        "unregistered_skill_executions",
        "direct_tool_executions",
        "registry_bypasses",
        "readiness_violations",
        "unresolved_citations",
        "injection_violations",
        "recommendation_violations",
        "explicit_language_override_failures",
        "high_severity_contradictions",
        "payload_budget_violations",
    ],
)
def test_each_critical_violation_rejects_even_with_high_average_support(metric):
    baseline = report()
    candidate = baseline.model_copy(
        update={"metrics": baseline.metrics.model_copy(update={metric: 1})}
    )
    gate = AgentReleaseGate().evaluate(candidate)
    assert gate.decision == "REJECTED"
    assert metric in gate.reasons


@pytest.mark.parametrize("change", ["offline", "incomplete", "missing-case", "missing-verdicts"])
def test_fake_runs_and_incomplete_evaluations_cannot_approve(change):
    baseline = report()
    if change == "offline":
        candidate = baseline.model_copy(update={"mode": "offline"})
    elif change == "incomplete":
        candidate = baseline.model_copy(update={"status": "EVALUATION_INCOMPLETE"})
    elif change == "missing-case":
        candidate = baseline.model_copy(update={"cases": baseline.cases[:-1]})
    else:
        rows = (baseline.cases[0].model_copy(update={"claim_evaluations": ()}), *baseline.cases[1:])
        candidate = baseline.model_copy(update={"cases": rows, "metrics": aggregate_metrics(rows)})
    assert AgentReleaseGate().evaluate(candidate).decision == "CONDITIONAL"


def test_distributions_preserve_missing_usage_and_nearest_rank_p95():
    assert distribution([]).sample_count == 0
    assert distribution([]).total is None
    result = distribution(list(range(1, 21)))
    assert (result.sample_count, result.total, result.mean, result.median, result.p95) == (
        20,
        210,
        10.5,
        10.5,
        19,
    )


def test_ambiguous_cases_are_excluded_and_insufficient_is_not_supported():
    baseline = report()
    row = baseline.cases[0].model_copy(
        update={"ambiguity_class": "AMBIGUOUS", "routing_pass": False}
    )
    metrics = aggregate_metrics((row, *baseline.cases[1:]))
    assert metrics.routing.strict_case_count == 19
    assert metrics.routing.strict_routing_accuracy == 1
    assert metrics.routing.ambiguous_cases == (row.case_id,)


def test_small_unregistered_subset_cannot_approve_by_rewriting_expected_ids():
    baseline = report()
    rows = baseline.cases[:3]
    candidate = baseline.model_copy(
        update={
            "cases": rows,
            "expected_case_ids": tuple(c.case_id for c in rows),
            "metrics": aggregate_metrics(rows),
        }
    )
    assert AgentReleaseGate().evaluate(candidate).decision == "CONDITIONAL"


def test_one_high_severity_contradiction_rejects_even_at_95_percent_support():
    baseline = report()
    evaluation = (
        baseline.cases[0]
        .claim_evaluations[0]
        .model_copy(
            update={
                "verdict": "CONTRADICTED",
                "severity": "HIGH",
                "reason_code": "EVIDENCE_CONTRADICTION",
            }
        )
    )
    rows = (
        baseline.cases[0].model_copy(update={"claim_evaluations": (evaluation,)}),
        *baseline.cases[1:],
    )
    candidate = baseline.model_copy(update={"cases": rows, "metrics": aggregate_metrics(rows)})
    assert candidate.metrics.claim_support_rate == 0.95
    assert candidate.metrics.high_severity_contradictions == 1
    assert AgentReleaseGate().evaluate(candidate).decision == "REJECTED"


@pytest.mark.parametrize(
    "change", ["missing", "offline", "model", "hash", "incomplete", "wrong-verdict"]
)
def test_v2_calibration_is_required_and_cannot_approve_unqualified_judge(change):
    baseline = report()
    calibration = baseline.judge_calibration
    assert calibration is not None
    if change == "missing":
        calibration = None
    elif change == "offline":
        calibration = calibration.model_copy(update={"mode": EvalMode.OFFLINE})
    elif change == "model":
        calibration = calibration.model_copy(update={"model": "different-judge"})
    elif change == "hash":
        calibration = calibration.model_copy(update={"manifest_hash": "0" * 64})
    elif change == "incomplete":
        calibration = calibration.model_copy(update={"cases": calibration.cases[:-1]})
    else:
        row = calibration.cases[0]
        changed = row.model_copy(
            update={"evaluation": row.evaluation.model_copy(update={"verdict": "INSUFFICIENT"})}
        )
        # The copied acceptable=True/accuracy=1.0 flags must not bypass actual wrong verdicts.
        calibration = calibration.model_copy(update={"cases": (changed, *calibration.cases[1:])})
    gate = AgentReleaseGate().evaluate(
        baseline.model_copy(update={"judge_calibration": calibration})
    )
    assert gate.decision == "CONDITIONAL" and "live_judge_calibration" in gate.reasons


def test_legacy_v1_gate_has_no_retroactive_calibration_requirement():
    baseline = report()
    legacy = baseline.model_copy(
        update={
            "manifest": baseline.manifest.model_copy(update={"judge_protocol_version": None}),
            "judge_calibration": None,
        }
    )
    gate = AgentReleaseGate().evaluate(legacy)
    assert gate.decision == "APPROVED"
    assert "live_judge_calibration" not in {c.rule for c in gate.checks}
