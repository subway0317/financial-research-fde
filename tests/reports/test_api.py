import pytest
from fastapi.testclient import TestClient

from financial_research.api.app import create_app
from financial_research.exceptions import ConfigurationError, ProviderError, UnknownTickerError
from financial_research.llm.errors import AgentConfigurationError, LLMProviderError
from financial_research.public_research.schemas import PublicEquityResearchReportResponse
from financial_research.reports.errors import ReportCompilationError, ReportIntegrityError

from .conftest import REQUEST

ENDPOINT = "/v1/reports/equity-research"
BODY = REQUEST.model_dump(mode="json")


@pytest.mark.parametrize("language", ["ENGLISH", "CHINESE"])
def test_report_api_is_typed_stateless_and_never_writes_bundles(
    report_agent_factory, monkeypatch, tmp_path, language
):
    monkeypatch.chdir(tmp_path)
    agent, llm, _ = report_agent_factory()
    with TestClient(create_app(agent_factory=lambda: agent)) as client:
        response = client.post(ENDPOINT, json={**BODY, "response_language": language})
    assert response.status_code == 200 and response.headers["X-Request-ID"]
    parsed = PublicEquityResearchReportResponse.model_validate(response.json())
    assert parsed.report.language == language and parsed.manifest_summary.synthesis_call_count == 1
    assert parsed.report.status == "COMPLETED_WITH_WARNINGS"
    assert llm.call_count == 1
    assert not (tmp_path / "artifacts").exists() and list(tmp_path.iterdir()) == []
    assert "bundle_path" not in response.text


def test_report_api_blocked_is_200_with_no_llm_calls(report_agent_factory, nvda_context):
    agent, llm, _ = report_agent_factory(context=nvda_context, replies=[])
    with TestClient(create_app(agent_factory=lambda: agent)) as client:
        response = client.post(ENDPOINT, json=BODY)
    assert response.status_code == 200
    data = PublicEquityResearchReportResponse.model_validate(response.json())
    assert data.report.status == "BLOCKED" and data.report.blocking_reasons
    assert data.manifest_summary.claim_count == llm.call_count == 0


@pytest.mark.parametrize(
    "updates",
    [
        {"intent": "MARKET_FOCUS"},
        {"selected_skill_id": "market_analysis"},
        {"question": "Buy NVDA"},
        {"provider": "other"},
        {"response_language": "AUTO"},
        {"as_of_date": "2025-05-25T00:00:00Z"},
        {"ticker": "../../bad"},
    ],
)
def test_bad_input_rejected_before_configuration_or_factory(monkeypatch, updates):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def forbidden_factory():
        raise AssertionError("invalid requests must not construct an Agent")

    with TestClient(create_app(agent_factory=forbidden_factory)) as client:
        response = client.post(ENDPOINT, json={**BODY, **updates})
    assert (
        response.status_code == 422 and response.json()["error_code"] == "REQUEST_VALIDATION_ERROR"
    )


def test_report_default_config_is_missing_and_openapi_has_explicit_language_contract(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with TestClient(create_app()) as client:
        schema = client.get("/openapi.json").json()
        response = client.post(ENDPOINT, json=BODY)
        assert client.get("/health").status_code == 200
        assert client.get("/docs").status_code == 200
    assert response.status_code == 503
    assert response.json()["error_code"] == "AGENT_CONFIGURATION_ERROR"
    properties = schema["components"]["schemas"]["EquityResearchReportRequest"]["properties"]
    assert set(properties) == {"ticker", "as_of_date", "response_language"}
    assert properties["response_language"]["$ref"] == "#/components/schemas/ReportLanguage"
    assert schema["components"]["schemas"]["ReportLanguage"]["enum"] == ["ENGLISH", "CHINESE"]
    assert properties["response_language"]["default"] == "ENGLISH"
    assert set(schema["paths"]) == {
        "/health",
        "/v1/agent/research",
        ENDPOINT,
        *(
            f"/v1/research/{name}"
            for name in (
                "company-snapshot",
                "fundamental-trends",
                "compare-periods",
                "market-behavior",
                "quality",
            )
        ),
    }


@pytest.mark.parametrize(
    "error,status,code",
    [
        (UnknownTickerError, 404, "UNKNOWN_TICKER"),
        (ProviderError, 502, "PROVIDER_ERROR"),
        (ConfigurationError, 503, "AGENT_CONFIGURATION_ERROR"),
    ],
)
def test_report_maps_real_skill_failure_path(report_agent_factory, error, status, code):
    agent, llm, _ = report_agent_factory(builder_error=error("__PRIVATE_PROVIDER_SECRET__"))
    with TestClient(
        create_app(agent_factory=lambda: agent), raise_server_exceptions=False
    ) as client:
        response = client.post(ENDPOINT, json=BODY)
    assert response.status_code == status and response.json()["error_code"] == code
    assert llm.call_count == 0 and "__PRIVATE_PROVIDER_SECRET__" not in response.text


@pytest.mark.parametrize(
    "error,status,code",
    [
        (ReportCompilationError, 500, "REPORT_COMPILATION_ERROR"),
        (ReportIntegrityError, 500, "REPORT_INTEGRITY_ERROR"),
        (AgentConfigurationError, 503, "AGENT_CONFIGURATION_ERROR"),
        (LLMProviderError, 502, "LLM_PROVIDER_ERROR"),
    ],
)
def test_report_api_errors_are_sanitized(error, status, code):
    def broken_factory():
        raise error("__SECRET_KEY__ __SEC_CONTACT__ raw-provider-message")

    with TestClient(
        create_app(agent_factory=broken_factory), raise_server_exceptions=False
    ) as client:
        response = client.post(ENDPOINT, json=BODY)
    assert response.status_code == status and response.json()["error_code"] == code
    assert all(
        secret not in response.text
        for secret in ("__SECRET_KEY__", "__SEC_CONTACT__", "raw-provider-message")
    )


def test_repeated_api_runs_have_distinct_runs_same_semantic_report(report_agent_factory):
    with TestClient(create_app(agent_factory=lambda: report_agent_factory()[0])) as client:
        first = client.post(ENDPOINT, json=BODY).json()
        second = client.post(ENDPOINT, json=BODY).json()
    assert first["report"]["run_id"] != second["report"]["run_id"]
    assert first["report"]["report_id"] == second["report"]["report_id"]


def test_actual_grounding_failure_returns_safe_500_no_report(report_agent_factory):
    agent, llm, _ = report_agent_factory(replies=["broken", "broken"])
    with TestClient(
        create_app(agent_factory=lambda: agent), raise_server_exceptions=False
    ) as client:
        response = client.post(ENDPOINT, json=BODY)
    assert (
        response.status_code == 500
        and response.json()["error_code"] == "GROUNDING_VALIDATION_ERROR"
    )
    assert llm.call_count == 2 and "report" not in response.json()
