"""Auditable local artifacts with exclusive run creation and preserved live baselines."""

import json
from pathlib import Path

from financial_research.evals.schemas import (
    EvalCaseResult,
    EvalMode,
    EvalRunArtifact,
    EvaluationReport,
    FrozenManifest,
)


def normalized_report(report: EvaluationReport) -> str:
    def normalize(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: normalize(item)
                for key, item in value.items()
                if key not in {"run_id", "started_at", "completed_at", "latency_ms", "duration_ms"}
            }
        if isinstance(value, list):
            return [normalize(item) for item in value]
        return value

    return json.dumps(
        normalize(report.model_dump(mode="json")), sort_keys=True, separators=(",", ":")
    )


def markdown_report(report: EvaluationReport) -> str:
    lines = [
        f"# Agent evaluation: {report.run_id}",
        "",
        f"Suite: `{report.suite_version}` | mode: `{report.mode}` | subset: `{report.subset}`",
        f"Evaluation status: **{report.status}** | "
        f"model release gate: **{report.release_gate.decision}**",
        f"Checkpoint: `{report.manifest.code_checkpoint}` | dirty: `{report.manifest.code_dirty}`",
        f"Production code hash: `{report.manifest.production_code_hash}`",
        f"Manifest hash: `{report.manifest.manifest_hash}`",
        f"Threshold hash: `{report.manifest.threshold_config_hash}`",
        f"Model: `{report.model}` | judge: `{report.judge_model}` | "
        f"same model: `{report.same_model_judge}`",
        f"Prompts: `{report.manifest.planner_prompt_version}`, "
        f"`{report.manifest.synthesis_prompt_version}`, `{report.manifest.judge_prompt_version}`",
        "",
        "Offline scripted outcomes validate infrastructure and do not qualify a real model.",
        "The semantic Judge can be wrong. v2 requires an independent live calibration; "
        "a small calibration set does not establish general grading accuracy.",
        "Same-model judging may share systematic errors with the model under evaluation.",
        "",
        "## Deterministic and semantic metrics",
        "",
        "```json",
        report.metrics.model_dump_json(indent=2),
        "```",
        "",
        "## Release rules",
        "",
        "| Rule | Observed | Threshold | Result |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {c.rule} | {c.observed} | {c.threshold} | {'PASS' if c.passed else 'FAIL'} |"
        for c in report.release_gate.checks
    )
    lines.extend(
        (
            "",
            "## Operational metrics",
            "",
            "Token aggregates are per reported LLM call; unknown usage remains null.",
            "Latency is per evaluated case, including Agent and Judge. "
            "p95 uses nearest rank; each statistic records its sample count.",
            "No USD price estimate is used.",
            "",
            "```json",
            report.operational.model_dump_json(indent=2),
            "```",
            "",
            "## Cases",
            "",
            "| Case | Class | Intent | Skill | Evaluation | Agent | Claims | Error |",
            "| --- | --- | --- | --- | --- | --- | ---: | --- |",
        )
    )
    lines.extend(
        f"| {c.case_id} | {c.ambiguity_class} | {c.actual_intent} | {c.actual_skill} | "
        f"{c.status} | {c.agent_status} | {c.claim_count} | {c.error_code or ''} |"
        for c in report.cases
    )
    lines.extend(
        (
            "",
            "English and Chinese are formally supported and evaluated; "
            "other languages are best effort.",
            "Original evidence identifiers and canonical diagnostic audit text remain verbatim.",
            "Frozen fixtures are synthetic. Financial-provider integration "
            "is checked separately by E2E smoke.",
            "",
        )
    )
    return "\n".join(lines)


class ArtifactWriter:
    def __init__(
        self,
        root: Path,
        *,
        run_id: str,
        mode: EvalMode,
        manifest: FrozenManifest,
        model: str,
        judge_model: str,
    ) -> None:
        self.directory = root / run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.run_id, self.mode, self.manifest, self.model, self.judge_model = (
            run_id,
            mode,
            manifest,
            model,
            judge_model,
        )
        (self.directory / "frozen_manifest.json").write_text(
            manifest.model_dump_json(indent=2) + "\n"
        )
        self.progress(())

    def preserve_first_live_baseline(self) -> None:
        # Exclusive creation, even for external-block/partial runs. Later runs never overwrite it.
        pointer = self.directory.parent / f"first-live-{self.manifest.suite_version}.json"
        try:
            with pointer.open("x") as handle:
                json.dump(
                    {"run_id": self.run_id, "manifest_hash": self.manifest.manifest_hash},
                    handle,
                    indent=2,
                )
                handle.write("\n")
        except FileExistsError:
            pass

    def progress(self, cases: tuple[EvalCaseResult, ...], *, finished: bool = False) -> None:
        if (self.directory / "evaluation_report.json").exists():
            raise FileExistsError("completed evaluation artifacts cannot be overwritten")
        artifact = EvalRunArtifact(
            run_id=self.run_id,
            suite_version=self.manifest.suite_version,
            mode=self.mode,
            manifest_hash=self.manifest.manifest_hash,
            model=self.model,
            judge_model=self.judge_model,
            finished=finished,
            cases=cases,
        )
        temporary = self.directory / "eval_run.tmp"
        temporary.write_text(artifact.model_dump_json(indent=2) + "\n")
        temporary.replace(self.directory / "eval_run.json")

    def finish(self, report: EvaluationReport) -> None:
        self.progress(report.cases, finished=True)
        with (self.directory / "evaluation_report.json").open("x") as handle:
            handle.write(report.model_dump_json(indent=2) + "\n")
        with (self.directory / "evaluation_report.md").open("x") as handle:
            handle.write(markdown_report(report))
