import json
import sys

import pytest

from financial_research.agent.evidence_projection import project_evidence
from financial_research.evals import calibration
from financial_research.evals.calibration import (
    calibration_projection,
    calibration_qualifies,
    load_calibration,
    run_calibration,
)
from financial_research.evals.dataset import DEFAULT_ROOT, freeze_manifest
from financial_research.evals.fixtures import fixture_registry, load_fixtures
from financial_research.evals.judge import JUDGE_PROMPT, JUDGE_PROMPT_V1, JUDGE_PROMPT_VERSION
from financial_research.evals.schemas import EvalMode
from financial_research.llm.errors import LLMProviderError
from financial_research.llm.fake import FakeLLMClient


def test_calibration_is_independent_typed_bilingual_and_all_verdicts():
    data = load_calibration()
    assert len(data.cases) == 26
    assert data.calibration_version == "stage5-judge-calibration-v2"
    assert {c.language for c in data.cases} == {"ENGLISH", "CHINESE"}
    assert {c.expected_verdict for c in data.cases} == {"SUPPORTED", "CONTRADICTED", "INSUFFICIENT"}
    assert JUDGE_PROMPT_VERSION == "stage5-claim-support-judge-v2"
    assert "missing evidence is INSUFFICIENT" in JUDGE_PROMPT_V1
    assert "Missing context is not a contradiction" in JUDGE_PROMPT


def test_offline_calibration_preserves_labels_but_cannot_qualify_a_real_judge():
    manifest = freeze_manifest()
    report = run_calibration(
        run_id="scripted", mode=EvalMode.OFFLINE, manifest=manifest, model="scripted"
    )
    assert report.accuracy == 1.0 and report.acceptable
    assert len(report.cases) == 26
    assert report.confusion_counts == {
        "SUPPORTED->SUPPORTED": 17,
        "CONTRADICTED->CONTRADICTED": 3,
        "INSUFFICIENT->INSUFFICIENT": 6,
    }
    assert not calibration_qualifies(report, manifest, "scripted")
    assert all(c.usage[0].input_tokens is None for c in report.cases)


def test_missing_state_remains_missing_not_a_fabricated_contradiction():
    data = load_calibration()
    fixture = load_fixtures(DEFAULT_ROOT)["warnings"]
    projection = project_evidence(
        fixture_registry(fixture)
        .get("fundamental_analysis")
        .run(ticker=fixture.context.ticker, as_of_date=fixture.context.as_of_date)
    )
    full = calibration_projection(
        next(c for c in data.cases if c.case_id == "computed-supported-en"), projection
    )
    missing = calibration_projection(
        next(c for c in data.cases if c.case_id == "computed-missing-state-en"), projection
    )
    assert any(a.category == "COMPARISON_STATE" for a in full.support_index.values())
    assert not any(a.category == "COMPARISON_STATE" for a in missing.support_index.values())
    assert all(c.expected_verdict == "INSUFFICIENT" for c in data.cases if c.withheld_categories)
    assert set(missing.claims[0].evidence_ids) <= missing.support_index.keys()


def test_surprising_baseline_patterns_have_matching_source_values_and_no_label_override():
    report = run_calibration(
        run_id="patterns", mode=EvalMode.OFFLINE, manifest=freeze_manifest(), model="scripted"
    )
    patterns = [r for r in report.cases if r.case_id.startswith("baseline-surprising")]
    assert len(patterns) == 2
    for row in patterns:
        sources = [a.evidence for a in row.support_projection.support_index.values() if a.evidence]
        assert {(e.metric, str(e.value)) for e in sources} >= {
            ("revenue", "150"),
            ("net_income", "150"),
            ("net_income", "-100"),
        }


def all_supported(request):
    claims = json.loads(request.user_payload)["claims"]
    return json.dumps(
        {
            "evaluations": [
                {
                    "claim_id": c["claim_id"],
                    "verdict": "SUPPORTED",
                    "severity": "LOW",
                    "reason_code": "DIRECT_EVIDENCE_SUPPORT",
                    "evidence_ids": c["evidence_ids"],
                }
                for c in claims
            ]
        }
    )


def test_inaccurate_judge_is_detected_without_changing_calibration_labels():
    client = FakeLLMClient([all_supported] * 26)
    report = run_calibration(
        run_id="wrong",
        mode=EvalMode.LIVE,
        manifest=freeze_manifest(),
        model="scripted",
        client=client,
    )
    assert report.accuracy == 17 / 26 and not report.acceptable
    assert report.confusion_counts["CONTRADICTED->SUPPORTED"] == 3
    assert report.confusion_counts["INSUFFICIENT->SUPPORTED"] == 6
    assert not calibration_qualifies(report, freeze_manifest(), "scripted")


def test_calibration_provider_failure_stops_preserves_usage_and_does_not_invent_verdicts():
    client = FakeLLMClient([LLMProviderError("private credential-like diagnostic")])
    report = run_calibration(
        run_id="blocked",
        mode=EvalMode.LIVE,
        manifest=freeze_manifest(),
        model="scripted",
        client=client,
    )
    assert report.status == "EXTERNAL_BLOCKED" and len(report.cases) == 1
    assert report.cases[0].evaluation is None and client.call_count == 1
    assert report.accuracy is None and not report.acceptable
    assert "private credential-like" not in report.model_dump_json()


def test_missing_configuration_creates_safe_report_without_client_or_sec(monkeypatch, tmp_path):
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_EVAL_MODEL", "SEC_USER_AGENT"):
        monkeypatch.delenv(name, raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("client must not be constructed")

    monkeypatch.setattr(calibration, "OpenAIResponsesClient", forbidden)
    monkeypatch.setattr(
        sys,
        "argv",
        ["calibration", "--mode", "live", "--run-id", "missing", "--artifacts-dir", str(tmp_path)],
    )
    with pytest.raises(SystemExit) as result:
        calibration.main()
    assert result.value.code == 3
    data = json.loads((tmp_path / "missing/calibration_report.json").read_text())
    assert data["status"] == "USER_CONFIGURATION_REQUIRED" and data["cases"] == []


def test_calibration_artifacts_cannot_be_overwritten(tmp_path):
    report = run_calibration(
        run_id="immutable", mode=EvalMode.OFFLINE, manifest=freeze_manifest(), model="scripted"
    )
    calibration.write_calibration(report, tmp_path / "immutable")
    with pytest.raises(FileExistsError):
        calibration.write_calibration(report, tmp_path / "immutable")


@pytest.mark.parametrize("override", [None, "separate-judge"])
def test_live_calibration_selects_eval_model_or_falls_back_without_agent_calls(
    override, monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")
    monkeypatch.setenv("OPENAI_MODEL", "agent-model")
    if override:
        monkeypatch.setenv("OPENAI_EVAL_MODEL", override)
    else:
        monkeypatch.delenv("OPENAI_EVAL_MODEL", raising=False)
    chosen = []

    class BlockedAdapter:
        provider = "openai"

        def __init__(self, config):
            self.model = config.model
            chosen.append(config)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def generate(self, *args):
            raise LLMProviderError("private unavailable diagnostic")

    monkeypatch.setattr(calibration, "OpenAIResponsesClient", BlockedAdapter)
    monkeypatch.setattr(
        sys,
        "argv",
        ["calibration", "--mode", "live", "--run-id", "blocked", "--artifacts-dir", str(tmp_path)],
    )
    with pytest.raises(SystemExit) as result:
        calibration.main()
    assert result.value.code == 2
    assert len(chosen) == 1 and chosen[0].model == (override or "agent-model")
    output = capsys.readouterr().out
    assert '"expected_calls": 26' in output
    assert "test-placeholder" not in output and "private unavailable" not in output
