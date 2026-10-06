import json
import shutil

import pytest
from pydantic import ValidationError

from financial_research.evals.dataset import (
    DEFAULT_ROOT,
    freeze_manifest,
    load_suite,
    verify_manifest,
)
from financial_research.evals.fixtures import fixture_registry, load_fixtures
from financial_research.evals.schemas import EvalSuite
from financial_research.skills.readiness import synthesis_readiness


def test_versioned_dataset_coverage_and_no_live_provider_dependency():
    suite, thresholds = load_suite()
    assert suite.suite_version == "stage5-agent-eval-v1"
    assert len(suite.cases) == 40
    assert sum(c.ambiguity_class == "STRICT" for c in suite.cases) == 38
    assert sum("live-core" in c.tags for c in suite.cases) == 18
    assert {c.suite for c in suite.cases if "live-core" in c.tags} == {c.suite for c in suite.cases}
    assert (DEFAULT_ROOT / "protocol-lock.json").is_file()
    assert {c.suite for c in suite.cases} == {
        "routing",
        "readiness",
        "multilingual",
        "guardrails",
        "grounding",
    }
    assert thresholds.strict_routing_accuracy_min == 0.95
    assert thresholds.claim_support_rate_min == 0.95
    assert thresholds.max_synthesis_payload_bytes == 200000


def test_duplicate_ids_and_forced_ambiguous_labels_fail():
    suite, _ = load_suite()
    with pytest.raises(ValidationError, match="duplicate case IDs"):
        EvalSuite(suite_version=suite.suite_version, cases=(*suite.cases[:-1], suite.cases[0]))
    case = suite.cases[0]
    with pytest.raises(ValidationError, match="ambiguous"):
        type(case).model_validate({**case.model_dump(), "ambiguity_class": "AMBIGUOUS"})


@pytest.mark.parametrize(
    "field,value", [("fixture_scenario", "absent"), ("expected_skill_id", "discounted_cash_flow")]
)
def test_invalid_fixture_or_skill_references_fail(tmp_path, field, value):
    root = tmp_path / "evals"
    shutil.copytree(DEFAULT_ROOT, root)
    path = root / "cases/routing.json"
    data = json.loads(path.read_text())
    data[0][field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_suite(root)


def test_fixture_scenarios_cover_actual_readiness_and_are_reusable():
    fixtures = load_fixtures(DEFAULT_ROOT)
    observed = {}
    for name, fixture in fixtures.items():
        registry = fixture_registry(fixture)
        result = registry.get("research_quality_audit").run(
            ticker=fixture.context.ticker, as_of_date=fixture.context.as_of_date
        )
        observed[name] = synthesis_readiness(result)
        assert fixture.context.model_dump_json() == fixtures[name].context.model_dump_json()
    assert observed == {"pass": "READY", "warnings": "READY_WITH_WARNINGS", "fail": "NOT_READY"}


def test_manifest_hashes_are_stable_and_tampering_is_rejected(tmp_path):
    manifest = freeze_manifest()
    assert manifest == freeze_manifest()
    verify_manifest(manifest)
    assert len(manifest.case_versions) == 40
    assert len(manifest.fixture_hashes) == 3
    assert len(manifest.live_core_ids) == 18
    assert manifest.judge_prompt_version == "stage5-claim-support-judge-v2"
    assert manifest.judge_protocol_version == "stage5-judge-protocol-v3"
    assert manifest.support_projection_version == "stage5-claim-support-projection-v3"
    assert manifest.calibration_version == "stage5-judge-calibration-v2"
    assert manifest.calibration_accuracy_min == 1.0
    root = tmp_path / "evals"
    shutil.copytree(DEFAULT_ROOT, root)
    path = root / "thresholds.json"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="manifest"):
        verify_manifest(manifest, root)
    with pytest.raises(ValueError, match="hash"):
        verify_manifest(manifest.model_copy(update={"manifest_hash": "0" * 64}))


def test_independent_calibration_hash_is_frozen_without_changing_agent_protocol(tmp_path):
    manifest = freeze_manifest()
    root = tmp_path / "evals"
    shutil.copytree(DEFAULT_ROOT, root)
    path = root / "calibration/stage5-judge-calibration-v2.json"
    path.write_text(path.read_text() + "\n")
    assert load_suite(root) == load_suite()
    with pytest.raises(ValueError, match="manifest"):
        verify_manifest(manifest, root)
