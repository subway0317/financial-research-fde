"""Provider-aware readiness and real Tiingo adapter failures at the public API."""

import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from reports.conftest import REQUEST

from financial_research.agent.service import ResearchAgent
from financial_research.config import ResearchConfig
from financial_research.deployment.app import create_production_app
from financial_research.deployment.config import DeploymentConfig
from financial_research.deployment.logging import OperationalFormatter
from financial_research.llm.fake import FakeLLMClient
from financial_research.providers.sec import SECProvider
from financial_research.providers.tiingo import TiingoMarketProvider
from financial_research.research.live import LiveContextBuilder
from financial_research.skills.defaults import create_skill_registry

from .conftest import SECRETS

SENTINEL = "__TIINGO_SECRET_SENTINEL__"


@pytest.mark.parametrize(
    "provider,token,expected",
    [
        ("yahoo", None, 200),
        ("tiingo", None, 503),
        ("tiingo", "", 503),
        ("tiingo", " ", 503),
        ("tiingo", SENTINEL, 200),
    ],
)
def test_provider_aware_readiness_without_network_or_secret_output(
    production_env, compiled_frontend, monkeypatch, provider, token, expected
):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", provider)
    if token is None:
        monkeypatch.delenv("TIINGO_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("TIINGO_API_TOKEN", token)
    settings = DeploymentConfig.from_env()
    app = create_production_app(deployment_config=settings, frontend_dir=compiled_frontend)
    with TestClient(app) as client:
        response = client.get("/ready")
        assert client.get("/health").status_code == 200
    assert response.status_code == expected
    assert ("TIINGO_CONFIG_UNAVAILABLE" in response.json()["codes"]) == (expected == 503)
    assert SENTINEL not in response.text + repr(settings)
    assert app.state.research_config.market_data_provider == provider


def test_injected_deployment_provider_matches_readiness_and_runtime(
    production_env, compiled_frontend
):
    settings = production_env.model_copy(
        update={"market_data_provider": "tiingo", "tiingo_api_token": SecretStr(SENTINEL)}
    )
    app = create_production_app(deployment_config=settings, frontend_dir=compiled_frontend)
    assert app.state.research_config.market_data_provider == "tiingo"
    assert app.state.research_config.tiingo_api_token.get_secret_value() == SENTINEL


@pytest.mark.parametrize("value", ["unknown", "marketstack", ""])
def test_invalid_deployment_provider_is_sanitized(production_env, monkeypatch, value):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", value)
    monkeypatch.setenv("TIINGO_API_TOKEN", SENTINEL)
    with pytest.raises(ValueError, match="Invalid deployment configuration") as error:
        DeploymentConfig.from_env()
    assert SENTINEL not in str(error.value)


@pytest.mark.parametrize(
    "operation,status",
    [
        (operation, status)
        for operation in ("fetch_market_metadata", "fetch_market_history")
        for status in (401, 403, 429, 500)
    ],
)
def test_tiingo_failure_crosses_live_composition_skill_agent_and_api_safely(
    production_env, compiled_frontend, provider_payloads, monkeypatch, caplog, operation, status
):
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.host == "api.tiingo.com":
            current = (
                "fetch_market_history"
                if request.url.path.endswith("/prices")
                else "fetch_market_metadata"
            )
            return (
                httpx.Response(status, text=SENTINEL)
                if current == operation
                else httpx.Response(200, json={"ticker": "NVDA", "exchangeCode": "NASDAQ"})
            )
        assert request.url.path.endswith("company_tickers_exchange.json")
        return httpx.Response(200, json=provider_payloads["directory"])

    with httpx.Client(transport=httpx.MockTransport(handle)) as upstream:
        monkeypatch.setattr(
            "financial_research.research.live.SECProvider",
            lambda **kw: SECProvider(client=upstream, **kw),
        )
        monkeypatch.setattr(
            "financial_research.research.live.TiingoMarketProvider",
            lambda **kw: TiingoMarketProvider(client=upstream, **kw),
        )
        builder = LiveContextBuilder(
            ResearchConfig(
                sec_user_agent="Test test@example.test",
                market_data_provider="tiingo",
                tiingo_api_token=SecretStr(SENTINEL),
            )
        )
        llm = FakeLLMClient([])
        agent = ResearchAgent(registry=create_skill_registry(builder), llm=llm)
        app = create_production_app(frontend_dir=compiled_frontend, agent_factory=lambda: agent)
        with TestClient(app) as client, caplog.at_level(logging.INFO):
            response = client.post(
                "/v1/reports/equity-research",
                json=REQUEST.model_dump(mode="json"),
                headers={"X-Demo-Access": SECRETS[1]},
            )
    assert response.status_code == 502 and response.json()["error_code"] == "PROVIDER_ERROR"
    assert llm.call_count == 0
    failures = [
        json.loads(OperationalFormatter().format(r))
        for r in caplog.records
        if getattr(r, "event", "") == "provider_failure"
    ]
    [failure] = failures
    assert failure["provider"] == "tiingo-eod" and failure["operation"] == operation
    assert failure["exception_type"] == "HTTPStatusError" and failure["upstream_status"] == status
    assert failure["request_id"] == response.headers["X-Request-ID"]
    assert SENTINEL not in response.text + caplog.text + json.dumps(failures)
    assert all(r.url.host != "query1.finance.yahoo.com" for r in requests)


def test_unknown_exchange_reaches_public_422_without_fallback(production_env, compiled_frontend):
    def handle(request):
        assert not request.url.path.endswith("/prices")
        return httpx.Response(200, json={"ticker": "NVDA", "exchangeCode": "UNKNOWN"})

    def factory():
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            TiingoMarketProvider(api_token=SENTINEL, client=client).get_market(
                "NVDA", REQUEST.as_of_date, REQUEST.as_of_date
            )
        raise AssertionError("unknown metadata must fail")

    app = create_production_app(frontend_dir=compiled_frontend, agent_factory=factory)
    with TestClient(app) as client:
        response = client.post(
            "/v1/reports/equity-research",
            json=REQUEST.model_dump(mode="json"),
            headers={"X-Demo-Access": SECRETS[1]},
        )
    assert response.status_code == 422 and response.json()["error_code"] == "DATA_VALIDATION_ERROR"
    assert SENTINEL not in response.text
