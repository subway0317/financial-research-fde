"""Strict dataset validation and content-addressed pre-live protocol manifests."""

import hashlib
import json
import subprocess
from pathlib import Path

from pydantic import TypeAdapter

from financial_research.agent.planner import INTENT_SKILLS
from financial_research.agent.prompts import (
    PLANNER_PROMPT_VERSION,
    SYNTHESIS_PROMPT_VERSION,
)
from financial_research.evals.fixtures import load_fixtures
from financial_research.evals.schemas import (
    AgentEvalCase,
    DatasetLock,
    EvalSuite,
    FrozenManifest,
    ReleaseThresholds,
)
from financial_research.skills.defaults import create_skill_registry

DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "evals"


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_suite(root: Path = DEFAULT_ROOT) -> tuple[EvalSuite, ReleaseThresholds]:
    cases: list[AgentEvalCase] = []
    for path in sorted((root / "cases").glob("*.json")):
        cases.extend(TypeAdapter(tuple[AgentEvalCase, ...]).validate_json(path.read_text()))
    suite = EvalSuite(
        suite_version="stage5-agent-eval-v1", cases=tuple(sorted(cases, key=lambda c: c.case_id))
    )
    thresholds = ReleaseThresholds.model_validate_json((root / "thresholds.json").read_text())
    fixtures = load_fixtures(root)
    skills = {definition.skill_id for definition in create_skill_registry().list()}
    for case in suite.cases:
        if case.expected_skill_id is not None and (
            case.expected_intent is None
            or case.expected_skill_id not in skills
            or case.expected_skill_id != INTENT_SKILLS[case.expected_intent]
        ):
            raise ValueError("expected routing must match the registered intent mapping")
        fixture = fixtures.get(case.fixture_scenario)
        if fixture is None:
            raise ValueError("unresolved fixture reference")
        if (case.ticker, case.as_of_date) != (fixture.context.ticker, fixture.context.as_of_date):
            raise ValueError("case identity does not match frozen fixture")
    lock_path = root / "protocol-lock.json"
    if lock_path.exists():
        lock = DatasetLock.model_validate_json(lock_path.read_text())
        if lock != protocol_lock(root, suite):
            raise ValueError("dataset protocol changed; version and freeze a new benchmark")
    return suite, thresholds


def protocol_lock(root: Path, suite: EvalSuite) -> DatasetLock:
    return DatasetLock(
        suite_version=suite.suite_version,
        case_versions={c.case_id: c.case_version for c in suite.cases},
        case_file_hashes={
            str(p.relative_to(root)): content_hash(p.read_bytes())
            for p in sorted((root / "cases").glob("*.json"))
        },
        fixture_hashes={
            str(p.relative_to(root)): content_hash(p.read_bytes())
            for p in sorted((root / "fixtures").glob("*.json"))
        },
        threshold_config_hash=content_hash((root / "thresholds.json").read_bytes()),
    )


def freeze_manifest(root: Path = DEFAULT_ROOT) -> FrozenManifest:
    from financial_research.evals.calibration import (
        CALIBRATION_ACCURACY_MIN,
        CALIBRATION_FILE,
        CALIBRATION_VERSION,
        load_calibration,
    )
    from financial_research.evals.judge import JUDGE_PROMPT_VERSION
    from financial_research.evals.support import JUDGE_PROTOCOL_VERSION, SUPPORT_PROJECTION_VERSION

    suite, _ = load_suite(root)
    load_calibration(root)
    repository = Path(__file__).resolve().parents[3]
    source = repository / "src/financial_research"
    checkpoint = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository, text=True
    ).strip()
    dirty = bool(
        subprocess.check_output(["git", "status", "--porcelain"], cwd=repository, text=True).strip()
    )
    code = {
        str(path.relative_to(source)): content_hash(path.read_bytes())
        for path in sorted(source.rglob("*.py"))
    }
    prompt_paths = {
        "agent": source / "agent/prompts.py",
        "judge": source / "evals/judge.py",
    }
    fields = {
        "suite_version": suite.suite_version,
        "code_checkpoint": checkpoint,
        "code_dirty": dirty,
        "production_code_hash": content_hash(canonical_json(code).encode()),
        "case_versions": {c.case_id: c.case_version for c in suite.cases},
        "case_file_hashes": {
            str(p.relative_to(root)): content_hash(p.read_bytes())
            for p in sorted((root / "cases").glob("*.json"))
        },
        "fixture_hashes": {
            str(p.relative_to(root)): content_hash(p.read_bytes())
            for p in sorted((root / "fixtures").glob("*.json"))
        },
        "threshold_config_hash": content_hash((root / "thresholds.json").read_bytes()),
        "planner_prompt_version": PLANNER_PROMPT_VERSION,
        "synthesis_prompt_version": SYNTHESIS_PROMPT_VERSION,
        "judge_prompt_version": JUDGE_PROMPT_VERSION,
        "prompt_hashes": {
            name: content_hash(path.read_bytes()) for name, path in prompt_paths.items()
        },
        "live_core_ids": tuple(c.case_id for c in suite.cases if "live-core" in c.tags),
        "judge_protocol_version": JUDGE_PROTOCOL_VERSION,
        "support_projection_version": SUPPORT_PROJECTION_VERSION,
        "calibration_version": CALIBRATION_VERSION,
        "calibration_file_hash": content_hash((root / CALIBRATION_FILE).read_bytes()),
        "calibration_accuracy_min": CALIBRATION_ACCURACY_MIN,
    }
    return FrozenManifest.model_validate(
        {**fields, "manifest_hash": content_hash(canonical_json(fields).encode())}
    )


def verify_manifest(manifest: FrozenManifest, root: Path = DEFAULT_ROOT) -> None:
    try:
        current = freeze_manifest(root)
    except ValueError:
        raise ValueError("frozen manifest no longer matches the dataset protocol") from None
    # Dirty status can change when ignored artifacts are produced; content hashes are authoritative.
    if manifest.model_dump(exclude={"code_dirty", "manifest_hash"}) != current.model_dump(
        exclude={"code_dirty", "manifest_hash"}
    ):
        raise ValueError("frozen manifest no longer matches cases, fixtures, thresholds or code")
    fields = manifest.model_dump(mode="json", exclude={"manifest_hash"}, exclude_none=True)
    if content_hash(canonical_json(fields).encode()) != manifest.manifest_hash:
        raise ValueError("manifest hash is invalid")
