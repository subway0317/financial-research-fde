import json
import sys

import pytest

from financial_research.agent.config import AgentRuntimeConfig
from financial_research.agent.planner import INTENT_REASONS
from financial_research.evals import cli
from financial_research.evals.comparison import compare_benchmarks, write_comparison
from financial_research.evals.dataset import DEFAULT_ROOT, freeze_manifest, load_suite
from financial_research.evals.fixtures import load_fixtures
from financial_research.evals.judge import ClaimSupportJudge
from financial_research.evals.offline import offline_agent_client, offline_judge_client
from financial_research.evals.reporting import ArtifactWriter, normalized_report
from financial_research.evals.runner import evaluate_case, run_suite
from financial_research.evals.schemas import EvalMode
from financial_research.llm.errors import LLMProviderError
from financial_research.llm.fake import FakeLLMClient


def offline_run(run_id="test-offline"):
    return run_suite(
        run_id=run_id,
        mode=EvalMode.OFFLINE,
        subset="all",
        manifest=freeze_manifest(),
        agent_client=offline_agent_client,
        judge_client=offline_judge_client,
        model="scripted",
        judge_model="scripted",
        judge_provider="fake",
    )


def test_complete_offline_benchmark_is_reproducible_and_not_a_model_release():
    first, second = offline_run(), offline_run("different-run")
    assert normalized_report(first) == normalized_report(second)
    assert first.status == "COMPLETED"
    assert len(first.cases) == 40
    assert first.metrics.routing.strict_correct_count == 38
    assert first.metrics.routing.ambiguous_cases == ("routing-ambiguous-en", "routing-ambiguous-zh")
    assert first.metrics.support_numerator == first.metrics.support_denominator == 39
    assert first.metrics.readiness_violations == 0
    assert first.metrics.explicit_language_override_failures == 0
    assert first.metrics.injection_violations == 0
    assert first.metrics.behavior_failures == 0
    assert first.operational.agent_llm_call_count == 79
    assert first.operational.judge_llm_call_count == 39
    assert first.operational.input_tokens.sample_count == 0
    assert first.release_gate.decision == "CONDITIONAL"
    blocked = next(c for c in first.cases if c.case_id == "readiness-fail")
    assert blocked.agent_status == "BLOCKED" and blocked.synthesis_call_count == 0


def test_judge_external_failure_retains_answer_and_has_no_fabricated_verdict():
    case = load_suite()[0].cases[0]
    result = evaluate_case(
        case,
        load_fixtures(DEFAULT_ROOT)[case.fixture_scenario],
        offline_agent_client(case),
        ClaimSupportJudge(FakeLLMClient([LLMProviderError("private-error")])),
        AgentRuntimeConfig(),
    )
    assert result.status == "EVALUATION_INCOMPLETE"
    assert result.answer is not None and result.claim_count == 1
    assert result.claim_evaluations == ()
    assert "private-error" not in result.model_dump_json()


def test_provider_block_stops_suite_without_retry_or_quality_label():
    clients = []

    def fail(case):
        client = FakeLLMClient([LLMProviderError("private-quota-diagnostic")])
        clients.append(client)
        return client

    result = run_suite(
        run_id="blocked",
        mode=EvalMode.LIVE,
        subset="live-core",
        manifest=freeze_manifest(),
        agent_client=fail,
        judge_client=offline_judge_client,
        model="fixture",
        judge_model="fixture",
        judge_provider="fake",
    )
    assert result.status == "EXTERNAL_BLOCKED" and len(result.cases) == 1
    assert len(clients) == 1 and clients[0].call_count == 1
    assert result.cases[0].claim_evaluations == ()
    assert result.release_gate.decision == "CONDITIONAL"
    assert "private-quota-diagnostic" not in result.model_dump_json()


def test_artifacts_and_first_live_baseline_cannot_be_overwritten(tmp_path):
    report = offline_run()
    writer = ArtifactWriter(
        tmp_path,
        run_id=report.run_id,
        mode=report.mode,
        manifest=report.manifest,
        model=report.model,
        judge_model=report.judge_model,
    )
    writer.preserve_first_live_baseline()
    pointer = tmp_path / f"first-live-{report.suite_version}.json"
    before = pointer.read_bytes()
    writer.finish(report)
    assert {p.name for p in writer.directory.iterdir()} == {
        "frozen_manifest.json",
        "eval_run.json",
        "evaluation_report.json",
        "evaluation_report.md",
    }
    assert "API_KEY" not in (writer.directory / "evaluation_report.json").read_text()
    with pytest.raises(FileExistsError):
        writer.finish(report)
    another = ArtifactWriter(
        tmp_path,
        run_id="second",
        mode=report.mode,
        manifest=report.manifest,
        model=report.model,
        judge_model=report.judge_model,
    )
    another.preserve_first_live_baseline()
    assert pointer.read_bytes() == before
    with pytest.raises(FileExistsError):
        ArtifactWriter(
            tmp_path,
            run_id=report.run_id,
            mode=report.mode,
            manifest=report.manifest,
            model=report.model,
            judge_model=report.judge_model,
        )


def test_live_cli_missing_keys_never_constructs_clients_or_requires_sec(
    monkeypatch, tmp_path, capsys
):
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "SEC_USER_AGENT"):
        monkeypatch.delenv(name, raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("missing configuration must not construct a client")

    monkeypatch.setattr(cli, "OpenAIResponsesClient", forbidden)
    monkeypatch.setattr(
        sys,
        "argv",
        ["eval", "--mode", "live", "--artifacts-dir", str(tmp_path), "--run-id", "missing-config"],
    )
    with pytest.raises(SystemExit) as exit:
        cli.main()
    assert exit.value.code == 3
    report = json.loads((tmp_path / "missing-config/evaluation_report.json").read_text())
    assert report["status"] == "USER_CONFIGURATION_REQUIRED"
    assert len(report["expected_case_ids"]) == 18 and report["cases"] == []
    assert not (tmp_path / "first-live-stage5-agent-eval-v1.json").exists()
    assert "SEC_USER_AGENT" not in capsys.readouterr().out


def test_configured_live_cli_requires_calibration_before_constructing_any_adapter(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.delenv("OPENAI_EVAL_MODEL", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("uncalibrated Judge must not start live requests")

    monkeypatch.setattr(cli, "OpenAIResponsesClient", forbidden)
    monkeypatch.setattr(
        sys,
        "argv",
        ["eval", "--mode", "live", "--artifacts-dir", str(tmp_path), "--run-id", "uncalibrated"],
    )
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 1
    output = capsys.readouterr().out
    assert "LIVE_JUDGE_CALIBRATION_REQUIRED" in output and "test-placeholder" not in output
    artifact = json.loads((tmp_path / "uncalibrated/evaluation_report.json").read_text())
    assert artifact["cases"] == [] and artifact["release_gate"]["decision"] == "CONDITIONAL"


def test_programmatic_live_runner_also_blocks_uncalibrated_judge_before_calls():
    def forbidden(*args):
        raise AssertionError("unqualified Judge must not trigger calls")

    result = run_suite(
        run_id="no-calibration",
        mode=EvalMode.LIVE,
        subset="live-core",
        manifest=freeze_manifest(),
        agent_client=forbidden,
        judge_client=forbidden,
        model="test-model",
        judge_model="test-model",
        judge_provider="openai",
    )
    assert result.status == "EVALUATION_INCOMPLETE" and not result.cases
    assert "live_judge_calibration" in result.release_gate.reasons


def test_comparison_preserves_missing_tokens_and_does_not_claim_fake_improvement(tmp_path):
    baseline, candidate = offline_run(), offline_run("candidate")
    comparison = compare_benchmarks(baseline, candidate)
    assert comparison.dataset_unchanged and comparison.agent_prompts_unchanged
    assert not comparison.comparable_live_assessments
    assert comparison.candidate.judge_tokens["input_tokens"].total is None
    assert comparison.candidate.metrics.total_substantive_claims == 39
    write_comparison(baseline, candidate, tmp_path)
    with pytest.raises(FileExistsError):
        write_comparison(baseline, candidate, tmp_path)


@pytest.mark.parametrize("case_id", ["guard-injection-dcf-en", "guard-injection-dcf-zh"])
def test_adversarial_planner_cannot_execute_unregistered_skill_in_either_language(case_id):
    case = next(c for c in load_suite()[0].cases if c.case_id == case_id)
    intent = case.expected_intent
    malicious = {
        "plan_version": "1.0",
        "intent": intent,
        "selected_skill_id": "discounted_cash_flow",
        "reason_code": INTENT_REASONS[intent],
        "ticker": case.ticker,
        "as_of_date": str(case.as_of_date),
        "requested_focus": None,
    }
    client = FakeLLMClient([json.dumps(malicious)] * 2)
    result = evaluate_case(
        case, load_fixtures(DEFAULT_ROOT)[case.fixture_scenario], client, None, AgentRuntimeConfig()
    )
    assert client.call_count == 2
    assert result.actual_skill is None and result.synthesis_call_count == 0
    assert result.unregistered_skill_executions == result.registry_bypasses == 0
    assert result.prompt_injection_pass is True
    assert result.error_code == "UNREGISTERED_SKILL"
