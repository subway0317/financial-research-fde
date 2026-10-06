"""Independent Judge calibration; scripted offline runs never qualify a real Judge."""

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from financial_research.agent.evidence_projection import project_evidence
from financial_research.evals.dataset import DEFAULT_ROOT, freeze_manifest, verify_manifest
from financial_research.evals.fixtures import fixture_registry, load_fixtures
from financial_research.evals.judge import (
    JUDGE_PROMPT_VERSION,
    ClaimSupportJudge,
    SemanticEvaluationError,
)
from financial_research.evals.schemas import (
    CalibrationCase,
    CalibrationDataset,
    CalibrationReport,
    CalibrationResult,
    EvalMode,
    EvalStatus,
    FrozenManifest,
)
from financial_research.evals.support import (
    SUPPORT_PROJECTION_VERSION,
    ClaimSupportProjection,
    project_claim_support,
    resolve_dependencies,
)
from financial_research.llm.base import LLMClient
from financial_research.llm.fake import FakeLLMClient
from financial_research.llm.openai_responses import OpenAIConfig, OpenAIResponsesClient
from financial_research.schemas.agent import EvidenceProjection

CALIBRATION_VERSION = "stage5-judge-calibration-v2"
CALIBRATION_FILE = "calibration/stage5-judge-calibration-v2.json"
CALIBRATION_ACCURACY_MIN = 1.0


def load_calibration(
    root: Path = DEFAULT_ROOT, *, version: str = CALIBRATION_VERSION
) -> CalibrationDataset:
    if version not in {"stage5-judge-calibration-v1", CALIBRATION_VERSION}:
        raise ValueError("unknown calibration version")
    return CalibrationDataset.model_validate_json(
        (root / "calibration" / f"{version}.json").read_text()
    )


def calibration_projection(
    case: CalibrationCase, projection: EvidenceProjection
) -> ClaimSupportProjection:
    support = project_claim_support((case.claim,), projection)
    retained = {
        key: value
        for key, value in support.support_index.items()
        if value.category not in case.withheld_categories
    }
    claim = support.claims[0]
    direct = set(claim.support_refs) & retained.keys()
    if not set(claim.evidence_ids) <= direct:
        raise ValueError("calibration cannot withhold an explicitly cited financial fact")
    closure = resolve_dependencies(direct, retained)
    return ClaimSupportProjection(
        claims=(
            claim.model_copy(
                update={
                    "support_refs": tuple(sorted(direct)),
                    "dependency_refs": tuple(sorted(closure - direct)),
                }
            ),
        ),
        support_index={key: retained[key] for key in sorted(closure)},
    )


def scripted_calibration_client(case: CalibrationCase) -> FakeLLMClient:
    """Known labels validate infrastructure, not semantic competence."""
    verdict = case.expected_verdict
    return FakeLLMClient(
        [
            json.dumps(
                {
                    "evaluations": [
                        {
                            "claim_id": case.claim.claim_id,
                            "verdict": verdict,
                            "severity": "HIGH"
                            if verdict == "CONTRADICTED"
                            else "MEDIUM"
                            if verdict == "INSUFFICIENT"
                            else "LOW",
                            "reason_code": "EVIDENCE_CONTRADICTION"
                            if verdict == "CONTRADICTED"
                            else "INSUFFICIENT_EVIDENCE"
                            if verdict == "INSUFFICIENT"
                            else "DIRECT_EVIDENCE_SUPPORT",
                            "evidence_ids": case.claim.evidence_ids,
                        }
                    ]
                }
            )
        ]
    )


def calibration_report(
    *,
    run_id: str,
    mode: EvalMode,
    manifest: FrozenManifest,
    model: str,
    provider: str,
    cases: tuple[CalibrationResult, ...],
    status: EvalStatus,
) -> CalibrationReport:
    dataset = load_calibration()
    evaluated = [c for c in cases if c.evaluation is not None]
    correct = sum(
        c.evaluation is not None and c.evaluation.verdict == c.expected_verdict for c in evaluated
    )
    confusion = Counter(
        f"{c.expected_verdict}->{c.evaluation.verdict}"
        for c in evaluated
        if c.evaluation is not None
    )
    accuracy = correct / len(evaluated) if evaluated else None
    complete = (
        status == "COMPLETED"
        and tuple(c.case_id for c in cases) == tuple(c.case_id for c in dataset.cases)
        and len(evaluated) == len(dataset.cases)
    )
    return CalibrationReport(
        run_id=run_id,
        mode=mode,
        status=status,
        manifest_hash=manifest.manifest_hash,
        production_code_hash=manifest.production_code_hash,
        calibration_version=CALIBRATION_VERSION,
        calibration_file_hash=hashlib.sha256(
            (DEFAULT_ROOT / CALIBRATION_FILE).read_bytes()
        ).hexdigest(),
        judge_prompt_version=JUDGE_PROMPT_VERSION,
        support_projection_version=SUPPORT_PROJECTION_VERSION,
        model=model,
        provider=provider,
        expected_case_ids=tuple(c.case_id for c in dataset.cases),
        cases=cases,
        accuracy=accuracy,
        confusion_counts=dict(sorted(confusion.items())),
        acceptable=complete and accuracy is not None and accuracy >= CALIBRATION_ACCURACY_MIN,
    )


def run_calibration(
    *,
    run_id: str,
    mode: EvalMode,
    manifest: FrozenManifest,
    model: str,
    client: LLMClient | None = None,
) -> CalibrationReport:
    verify_manifest(manifest)
    fixtures = load_fixtures(DEFAULT_ROOT)
    dataset = load_calibration()
    projections: dict[tuple[str, str], EvidenceProjection] = {}
    results: list[CalibrationResult] = []
    status = EvalStatus.COMPLETED
    if mode == "live" and client is None:
        raise ValueError("live calibration requires a real client")
    for case in dataset.cases:
        try:
            verify_manifest(manifest)
            key = (case.fixture_scenario, case.skill_id)
            if key not in projections:
                fixture = fixtures[case.fixture_scenario]
                result = (
                    fixture_registry(fixture)
                    .get(case.skill_id)
                    .run(ticker=fixture.context.ticker, as_of_date=fixture.context.as_of_date)
                )
                projections[key] = project_evidence(result)
            support = calibration_projection(case, projections[key])
            judge = ClaimSupportJudge(
                client if client is not None else scripted_calibration_client(case)
            )
            evaluations, usage = judge.evaluate_projection(support)
            results.append(
                CalibrationResult(
                    case_id=case.case_id,
                    expected_verdict=case.expected_verdict,
                    evaluation=evaluations[0],
                    support_projection=support,
                    usage=usage,
                )
            )
        except SemanticEvaluationError as exc:
            status = (
                EvalStatus.EXTERNAL_BLOCKED
                if exc.code == "JUDGE_PROVIDER_ERROR"
                else EvalStatus.EVALUATION_INCOMPLETE
            )
            results.append(
                CalibrationResult(
                    case_id=case.case_id,
                    expected_verdict=case.expected_verdict,
                    error_code=exc.code,
                    usage=exc.usage,
                )
            )
            break  # No calibration retries or repeated quota/outage calls.
        except (ValueError, KeyError):
            status = EvalStatus.EVALUATION_INCOMPLETE
            results.append(
                CalibrationResult(
                    case_id=case.case_id,
                    expected_verdict=case.expected_verdict,
                    error_code="CALIBRATION_SUPPORT_OR_PROTOCOL_ERROR",
                )
            )
            break
    try:
        verify_manifest(manifest)
    except ValueError:
        status = EvalStatus.EVALUATION_INCOMPLETE
    return calibration_report(
        run_id=run_id,
        mode=mode,
        manifest=manifest,
        model=model,
        provider=client.provider if client is not None else "fake",
        cases=tuple(results),
        status=status,
    )


def calibration_qualifies(
    report: CalibrationReport | None, manifest: FrozenManifest, model: str
) -> bool:
    if report is None:
        return False
    # Derive from actual verdicts, not a caller-provided acceptable/accuracy flag.
    try:
        dataset = load_calibration(version=manifest.calibration_version or "")
    except ValueError:
        return False
    expected = tuple(c.case_id for c in dataset.cases)
    return (
        report.mode == "live"
        and report.provider == "openai"
        and report.model == model
        and report.status == "COMPLETED"
        and report.expected_case_ids == expected
        and tuple(c.case_id for c in report.cases) == expected
        and all(
            c.evaluation is not None and c.evaluation.verdict == c.expected_verdict
            for c in report.cases
        )
        and all(
            c.expected_verdict == d.expected_verdict
            for c, d in zip(report.cases, dataset.cases, strict=True)
        )
        and report.manifest_hash == manifest.manifest_hash
        and report.production_code_hash == manifest.production_code_hash
        and report.calibration_file_hash == manifest.calibration_file_hash
        and report.judge_prompt_version == manifest.judge_prompt_version
        and report.support_projection_version == manifest.support_projection_version
        and report.calibration_version == manifest.calibration_version
        and all(
            len(c.usage) == 1
            and c.usage[0].success
            and c.usage[0].provider == "openai"
            and c.usage[0].model == model
            and c.usage[0].prompt_version == JUDGE_PROMPT_VERSION
            for c in report.cases
        )
    )


def write_calibration(report: CalibrationReport, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    with (directory / "calibration_report.json").open("x") as handle:
        handle.write(report.model_dump_json(indent=2) + "\n")
    lines = [
        f"# Judge calibration: {report.run_id}",
        "",
        f"Status: **{report.status}** | mode: `{report.mode}`",
        f"Model: `{report.model}` | prompt: `{report.judge_prompt_version}`",
        f"Accuracy: {report.accuracy} | complete and acceptable: {report.acceptable}",
        "Offline scripted calibration does not qualify a real Judge.",
        "",
        "```json",
        json.dumps(report.confusion_counts, indent=2),
        "```",
        "",
    ]
    with (directory / "calibration_report.md").open("x") as handle:
        handle.write("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["offline", "live"], default="offline")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument(
        "--artifacts-dir", type=Path, default=DEFAULT_ROOT.parent / "artifacts/evals"
    )
    args = parser.parse_args()
    try:
        manifest = (
            FrozenManifest.model_validate_json(args.manifest.read_text())
            if args.manifest
            else freeze_manifest()
        )
        verify_manifest(manifest)
        run_id = (
            args.run_id
            or f"judge-calibration-{args.mode}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
        )
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", run_id):
            raise ValueError("invalid run ID")
        directory = args.artifacts_dir / run_id
        if directory.exists():
            raise ValueError("completed calibration cannot be overwritten")
        mode = EvalMode(args.mode)
        model = (
            os.environ.get("OPENAI_EVAL_MODEL") or os.environ.get("OPENAI_MODEL") or ""
        ).strip()
        missing = mode == "live" and (not os.environ.get("OPENAI_API_KEY", "").strip() or not model)
        print(
            json.dumps(
                {
                    "calibration_version": CALIBRATION_VERSION,
                    "case_count": len(load_calibration().cases),
                    "expected_calls": len(load_calibration().cases),
                    "mode": mode,
                    "judge_model": "scripted"
                    if mode == "offline"
                    else "unconfigured"
                    if missing
                    else model,
                    "required_accuracy": CALIBRATION_ACCURACY_MIN,
                }
            ),
            flush=True,
        )
        if missing:
            report = calibration_report(
                run_id=run_id,
                mode=mode,
                manifest=manifest,
                model="unconfigured",
                provider="openai",
                cases=(),
                status=EvalStatus.USER_CONFIGURATION_REQUIRED,
            )
        elif mode == "offline":
            report = run_calibration(run_id=run_id, mode=mode, manifest=manifest, model="scripted")
        else:
            config = OpenAIConfig(
                model=model, timeout_seconds=os.environ.get("OPENAI_TIMEOUT_SECONDS", "120")
            )
            with OpenAIResponsesClient(config) as client:
                report = run_calibration(
                    run_id=run_id, mode=mode, manifest=manifest, model=model, client=client
                )
        write_calibration(report, directory)
        print(
            json.dumps(
                {
                    "status": report.status,
                    "accuracy": report.accuracy,
                    "acceptable": report.acceptable,
                    "artifact_directory": str(directory),
                }
            )
        )
        sys.exit(
            3
            if report.status == "USER_CONFIGURATION_REQUIRED"
            else 2
            if report.status == "EXTERNAL_BLOCKED"
            else 0
            if report.acceptable
            else 1
        )
    except (ValueError, OSError, ValidationError):
        print(
            json.dumps(
                {
                    "status": "EVALUATION_INCOMPLETE",
                    "error_code": "CALIBRATION_CONFIGURATION_PROTOCOL_OR_ARTIFACT_ERROR",
                }
            )
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
