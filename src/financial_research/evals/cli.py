"""Local offline or frozen-fixture live benchmark; only OpenAI is used in live mode."""

import argparse
import json
import os
import re
import sys
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from financial_research.evals.calibration import calibration_qualifies
from financial_research.evals.comparison import write_comparison
from financial_research.evals.dataset import (
    DEFAULT_ROOT,
    freeze_manifest,
    load_suite,
    verify_manifest,
)
from financial_research.evals.offline import offline_agent_client, offline_judge_client
from financial_research.evals.reporting import ArtifactWriter
from financial_research.evals.runner import build_report, run_suite
from financial_research.evals.schemas import (
    CalibrationReport,
    EvalMode,
    EvalStatus,
    EvaluationReport,
    FrozenManifest,
)
from financial_research.llm.errors import AgentConfigurationError
from financial_research.llm.openai_responses import OpenAIConfig, OpenAIResponsesClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", default="stage5-agent-eval-v1", choices=["stage5-agent-eval-v1"])
    parser.add_argument("--mode", default="offline", choices=["offline", "live"])
    parser.add_argument("--subset", choices=["all", "live-core"])
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--freeze-manifest", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument(
        "--artifacts-dir", type=Path, default=DEFAULT_ROOT.parent / "artifacts/evals"
    )
    parser.add_argument("--run-id")
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--calibration-report", type=Path)
    parser.add_argument("--compare-baseline", type=Path)
    args = parser.parse_args()
    mode = EvalMode(args.mode)
    subset = args.subset or ("live-core" if mode == "live" else "all")
    try:
        suite, thresholds = load_suite()
        manifest = (
            FrozenManifest.model_validate_json(args.manifest.read_text())
            if args.manifest
            else freeze_manifest()
        )
        verify_manifest(manifest)
        if args.freeze_manifest:
            args.freeze_manifest.parent.mkdir(parents=True, exist_ok=True)
            with args.freeze_manifest.open("x") as handle:
                handle.write(manifest.model_dump_json(indent=2) + "\n")
        selected = tuple(c for c in suite.cases if subset == "all" or "live-core" in c.tags)
        if mode == "live" and (subset != "live-core" or not 10 <= len(selected) <= 20):
            raise ValueError("live benchmark must use preregistered live-core")
        summary = {
            "suite_version": suite.suite_version,
            "case_count": len(selected),
            "mode": mode,
            "maximum_agent_calls": len(selected) * 4,
            "maximum_judge_calls": 0 if args.no_judge else len(selected),
            "judge_enabled": not args.no_judge,
            "manifest_hash": manifest.manifest_hash,
            "threshold_config_hash": manifest.threshold_config_hash,
        }
        print(json.dumps(summary, indent=2), flush=True)
        if args.validate_only:
            return
        run_id = args.run_id or f"{mode}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", run_id):
            raise ValueError("invalid run ID")
        missing = mode == "live" and any(
            not os.environ.get(name) for name in ("OPENAI_API_KEY", "OPENAI_MODEL")
        )
        model = (
            "scripted"
            if mode == "offline"
            else "unconfigured"
            if missing
            else OpenAIConfig.from_env().model
        )
        judge_model = (
            "scripted"
            if mode == "offline"
            else "unconfigured"
            if missing
            else os.environ.get("OPENAI_EVAL_MODEL") or model
        )
        calibration = (
            CalibrationReport.model_validate_json(args.calibration_report.read_text())
            if args.calibration_report
            else None
        )
        baseline = (
            EvaluationReport.model_validate_json(args.compare_baseline.read_text())
            if args.compare_baseline
            else None
        )
        writer = ArtifactWriter(
            args.artifacts_dir,
            run_id=run_id,
            mode=mode,
            manifest=manifest,
            model=model,
            judge_model=judge_model,
        )
        if missing:
            report = build_report(
                run_id=run_id,
                mode=mode,
                subset=subset,
                manifest=manifest,
                thresholds=thresholds,
                expected_ids=tuple(c.case_id for c in selected),
                cases=(),
                model=model,
                judge_provider="openai",
                judge_model=judge_model,
                judge_enabled=not args.no_judge,
                started_at=datetime.now(UTC),
                status=EvalStatus.USER_CONFIGURATION_REQUIRED,
            )
        elif mode == "offline":
            report = run_suite(
                run_id=run_id,
                mode=mode,
                subset=subset,
                manifest=manifest,
                agent_client=offline_agent_client,
                judge_client=None if args.no_judge else offline_judge_client,
                model=model,
                judge_model=judge_model,
                judge_provider="fake",
                progress=writer.progress,
            )
        else:
            if not calibration_qualifies(calibration, manifest, judge_model):
                report = build_report(
                    run_id=run_id,
                    mode=mode,
                    subset=subset,
                    manifest=manifest,
                    thresholds=thresholds,
                    expected_ids=tuple(c.case_id for c in selected),
                    cases=(),
                    model=model,
                    judge_provider="openai",
                    judge_model=judge_model,
                    judge_enabled=not args.no_judge,
                    started_at=datetime.now(UTC),
                    status=EvalStatus.EVALUATION_INCOMPLETE,
                    judge_calibration=calibration,
                )
                writer.finish(report)
                if baseline is not None:
                    write_comparison(baseline, report, writer.directory)
                print(
                    json.dumps(
                        {
                            "status": report.status,
                            "error_code": "LIVE_JUDGE_CALIBRATION_REQUIRED",
                            "artifact_directory": str(writer.directory),
                        }
                    )
                )
                sys.exit(1)
            with ExitStack() as stack:
                config = OpenAIConfig.from_env()
                judge_config = OpenAIConfig(
                    model=judge_model,
                    timeout_seconds=config.timeout_seconds,
                    max_output_tokens=config.max_output_tokens,
                )
                agent_adapter = stack.enter_context(OpenAIResponsesClient(config))
                judge_adapter = (
                    stack.enter_context(OpenAIResponsesClient(judge_config))
                    if not args.no_judge
                    else None
                )
                print(
                    json.dumps(
                        {
                            "model": model,
                            "judge_model": judge_model,
                            "same_model_judge": model == judge_model,
                        }
                    ),
                    flush=True,
                )
                writer.preserve_first_live_baseline()
                report = run_suite(
                    run_id=run_id,
                    mode=mode,
                    subset=subset,
                    manifest=manifest,
                    agent_client=lambda case: agent_adapter,
                    judge_client=(lambda: judge_adapter) if judge_adapter else None,
                    model=model,
                    judge_model=judge_model,
                    judge_provider="openai",
                    progress=writer.progress,
                    judge_calibration=calibration,
                )
        writer.finish(report)
        if baseline is not None:
            write_comparison(baseline, report, writer.directory)
        print(
            json.dumps(
                {
                    "status": report.status,
                    "release_decision": report.release_gate.decision,
                    "completed_cases": len(report.cases),
                    "artifact_directory": str(writer.directory),
                },
                indent=2,
            )
        )
        sys.exit(
            {
                EvalStatus.COMPLETED: 0,
                EvalStatus.USER_CONFIGURATION_REQUIRED: 3,
                EvalStatus.EXTERNAL_BLOCKED: 2,
                EvalStatus.EVALUATION_INCOMPLETE: 1,
            }[report.status]
        )
    except AgentConfigurationError:
        print(
            json.dumps(
                {"status": "USER_CONFIGURATION_REQUIRED", "error_code": "AGENT_CONFIGURATION_ERROR"}
            )
        )
        sys.exit(3)
    except (ValueError, OSError):
        print(
            json.dumps(
                {"status": "EVALUATION_INCOMPLETE", "error_code": "EVAL_PROTOCOL_OR_ARTIFACT_ERROR"}
            )
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
