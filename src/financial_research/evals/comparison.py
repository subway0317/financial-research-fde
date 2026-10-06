"""Read-only baseline comparison; keep offline and incomplete metrics distinguishable."""

from pathlib import Path

from financial_research.evals.metrics import distribution
from financial_research.evals.schemas import Distribution, EvalMetrics, EvaluationReport
from financial_research.schemas.base import CanonicalModel


class BenchmarkSnapshot(CanonicalModel):
    run_id: str
    mode: str
    status: str
    manifest_hash: str
    production_code_hash: str
    judge_prompt_version: str
    model: str
    judge_model: str
    release_decision: str
    metrics: EvalMetrics
    agent_tokens: dict[str, Distribution]
    judge_tokens: dict[str, Distribution]
    judge_latency_ms: Distribution
    total_latency_ms: Distribution


class BenchmarkComparison(CanonicalModel):
    baseline: BenchmarkSnapshot
    candidate: BenchmarkSnapshot
    dataset_unchanged: bool
    agent_prompts_unchanged: bool
    comparable_live_assessments: bool


def benchmark_snapshot(report: EvaluationReport) -> BenchmarkSnapshot:
    agent = [u for c in report.cases for u in c.agent_usage]
    judge = [u for c in report.cases for u in c.judge_usage]
    return BenchmarkSnapshot(
        run_id=report.run_id,
        mode=report.mode,
        status=report.status,
        manifest_hash=report.manifest.manifest_hash,
        production_code_hash=report.manifest.production_code_hash,
        judge_prompt_version=report.manifest.judge_prompt_version,
        model=report.model,
        judge_model=report.judge_model,
        release_decision=report.release_gate.decision,
        metrics=report.metrics,
        agent_tokens={
            field: distribution([v for u in agent if (v := getattr(u, field)) is not None])
            for field in ("input_tokens", "output_tokens", "total_tokens")
        },
        judge_tokens={
            field: distribution([v for u in judge if (v := getattr(u, field)) is not None])
            for field in ("input_tokens", "output_tokens", "total_tokens")
        },
        judge_latency_ms=distribution([u.latency_ms for u in judge]),
        total_latency_ms=distribution([c.latency_ms for c in report.cases]),
    )


def compare_benchmarks(
    baseline: EvaluationReport, candidate: EvaluationReport
) -> BenchmarkComparison:
    first, second = baseline.manifest, candidate.manifest
    dataset_unchanged = all(
        getattr(first, field) == getattr(second, field)
        for field in (
            "suite_version",
            "case_versions",
            "case_file_hashes",
            "fixture_hashes",
            "threshold_config_hash",
            "live_core_ids",
        )
    )
    prompts_unchanged = (
        first.planner_prompt_version == second.planner_prompt_version
        and first.synthesis_prompt_version == second.synthesis_prompt_version
        and first.prompt_hashes["agent"] == second.prompt_hashes["agent"]
    )
    return BenchmarkComparison(
        baseline=benchmark_snapshot(baseline),
        candidate=benchmark_snapshot(candidate),
        dataset_unchanged=dataset_unchanged,
        agent_prompts_unchanged=prompts_unchanged,
        comparable_live_assessments=dataset_unchanged
        and prompts_unchanged
        and all(
            r.mode == "live"
            and r.status == "COMPLETED"
            and r.judge_provider == "openai"
            and r.metrics.semantic_coverage == 1.0
            and tuple(c.case_id for c in r.cases) == first.live_core_ids
            for r in (baseline, candidate)
        ),
    )


def comparison_values(snapshot: BenchmarkSnapshot) -> dict[str, float | int | None]:
    m = snapshot.metrics
    return {
        "Routing accuracy": m.routing.strict_routing_accuracy,
        "Claim support rate": m.claim_support_rate,
        "SUPPORTED": m.supported_claims,
        "INSUFFICIENT": m.insufficient_claims,
        "CONTRADICTED": m.contradicted_claims,
        "HIGH contradictions": m.high_severity_contradictions,
        "Synthesis claims": m.total_substantive_claims,
        "Agent total tokens": snapshot.agent_tokens["total_tokens"].total,
        "Judge input tokens": snapshot.judge_tokens["input_tokens"].total,
        "Judge total tokens": snapshot.judge_tokens["total_tokens"].total,
        "Judge latency ms (total)": snapshot.judge_latency_ms.total,
        "Case latency ms (total)": snapshot.total_latency_ms.total,
    }


def write_comparison(
    baseline: EvaluationReport, candidate: EvaluationReport, directory: Path
) -> None:
    comparison = compare_benchmarks(baseline, candidate)
    with (directory / "baseline_comparison.json").open("x") as handle:
        handle.write(comparison.model_dump_json(indent=2) + "\n")
    lines = [
        "# Baseline comparison",
        "",
        f"Comparable complete live assessments: **{comparison.comparable_live_assessments}**",
        "An offline or incomplete candidate does not measure real model improvement.",
        "Judge protocols may differ; interpret semantic changes with calibration results.",
        "",
        "| Metric | Baseline | Candidate |",
        "| --- | --- | --- |",
    ]
    before, after = comparison_values(comparison.baseline), comparison_values(comparison.candidate)
    lines.extend(f"| {key} | {value} | {after[key]} |" for key, value in before.items())
    lines.extend(("", "Full deterministic invariants and distributions are in the JSON artifact."))
    with (directory / "baseline_comparison.md").open("x") as handle:
        handle.write("\n".join(lines) + "\n")
