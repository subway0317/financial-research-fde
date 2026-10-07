from financial_research.exceptions import ProviderError
from financial_research.llm.errors import LLMProviderError
from financial_research.reports.service import ReportWorkflowService
from financial_research.reports.smoke import run_live_report_smoke

from .conftest import REQUEST


def test_offline_report_smoke_covers_complete_pipeline(report_agent_factory, tmp_path):
    agent, llm, _ = report_agent_factory()
    result = run_live_report_smoke(REQUEST, tmp_path, service=ReportWorkflowService(agent))
    assert result["smoke_status"] == "PASS"
    assert result["status"] == "COMPLETED_WITH_WARNINGS"
    assert result["bundle_integrity"] == "PASS" and result["pit_violation_count"] == 0
    assert result["planner_calls"] == 0 and result["synthesis_calls"] == llm.call_count == 1
    assert (
        result["claim_count"] > 0
        and result["evidence_count"] > 0
        and result["calculation_count"] > 0
    )


def test_live_smoke_missing_configuration_has_no_provider_or_artifact(monkeypatch, tmp_path):
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "SEC_USER_AGENT", "OPENAI_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    result = run_live_report_smoke(REQUEST, tmp_path)
    assert result["smoke_status"] == "USER_CONFIGURATION_REQUIRED"
    assert set(result["missing_configuration"]) == {
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "SEC_USER_AGENT",
        "OPENAI_TIMEOUT_SECONDS",
    }
    assert list(tmp_path.iterdir()) == []


def test_blocked_bundle_is_valid_but_does_not_pass_live_smoke(
    report_agent_factory, nvda_context, tmp_path
):
    agent, _, _ = report_agent_factory(context=nvda_context)
    result = run_live_report_smoke(REQUEST, tmp_path, service=ReportWorkflowService(agent))
    assert result["smoke_status"] == "FAIL" and result["status"] == "BLOCKED"
    assert result["bundle_integrity"] == "PASS"


def test_external_failure_is_distinct_from_implementation_failure(report_agent_factory, tmp_path):
    agent, _, _ = report_agent_factory(builder_error=ProviderError("private-provider-payload"))
    result = run_live_report_smoke(REQUEST, tmp_path, service=ReportWorkflowService(agent))
    assert result["smoke_status"] == "EXTERNAL_BLOCKED"
    assert "private-provider-payload" not in str(result) and list(tmp_path.iterdir()) == []


def test_bad_llm_configuration_is_fail_not_external_outage(report_agent_factory, tmp_path):
    error = LLMProviderError("private-secret")
    error.http_status = 400
    agent, _, _ = report_agent_factory(replies=[error])
    result = run_live_report_smoke(REQUEST, tmp_path, service=ReportWorkflowService(agent))
    assert result["smoke_status"] == "FAIL" and "private-secret" not in str(result)
