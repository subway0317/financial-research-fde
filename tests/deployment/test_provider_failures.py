"""Offline provider failures traverse real adapters, Skills, Agent and API handlers."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from threading import Barrier
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from reports.conftest import REQUEST

from financial_research.agent.service import ResearchAgent
from financial_research.api.app import create_app
from financial_research.config import ResearchConfig
from financial_research.deployment.app import create_production_app
from financial_research.deployment.logging import OperationalFormatter
from financial_research.exceptions import DataValidationError, ProviderError
from financial_research.llm.fake import FakeLLMClient
from financial_research.provider_diagnostics import provider_failure_state
from financial_research.providers.http import JsonTransport
from financial_research.providers.market import YahooMarketProvider
from financial_research.providers.sec import SECProvider
from financial_research.research.live import LiveContextBuilder
from financial_research.skills.defaults import create_skill_registry

from .conftest import SECRETS

REPORT = "/v1/reports/equity-research"
BODY = REQUEST.model_dump(mode="json")
ACCESS = {"X-Demo-Access": SECRETS[1]}
UNSAFE_URL = "https://example.test/path?token=SECRET"
UNSAFE_BODY = "__ARBITRARY_RESPONSE_BODY__"
UNSAFE_HEADER = "Authorization: Bearer __HEADER_SECRET__"
UNSAFE_MESSAGE = " ".join((*SECRETS, UNSAFE_URL, UNSAFE_HEADER, UNSAFE_BODY))


@pytest.fixture
def failing_agent(monkeypatch, provider_payloads):
    with ExitStack() as stack:

        def create(operation, mode="status"):
            def handler(request):
                if request.url.host == "query1.finance.yahoo.com":
                    current, payload = "fetch_market_history", provider_payloads["market"]
                elif request.url.path.endswith("company_tickers_exchange.json"):
                    current, payload = "fetch_company_tickers", provider_payloads["directory"]
                elif "/companyfacts/" in request.url.path:
                    current, payload = "fetch_companyfacts", provider_payloads["fundamentals"]
                elif request.url.path.endswith("-submissions-001.json"):
                    current, payload = "fetch_submissions_archive", {}
                else:
                    assert request.url.path == "/submissions/CIK0001045810.json"
                    current = "fetch_submissions"
                    payload = {
                        "cik": "1045810",
                        "filings": {
                            "recent": {
                                key: []
                                for key in ("accessionNumber", "reportDate", "filingDate", "form")
                            },
                            "files": [
                                {
                                    "name": "CIK0001045810-submissions-001.json",
                                    "filingFrom": "2024-01-01",
                                    "filingTo": "2025-05-25",
                                }
                            ],
                        },
                    }
                if current != operation:
                    return httpx.Response(200, json=payload)
                if mode == "chart":
                    return httpx.Response(200, json={"chart": {"error": UNSAFE_MESSAGE}})
                unsafe_request = httpx.Request(
                    "GET", UNSAFE_URL, headers={"Authorization": UNSAFE_HEADER, **ACCESS}
                )
                if mode == "timeout":
                    raise httpx.ReadTimeout(UNSAFE_MESSAGE, request=unsafe_request)
                if mode == "raw_status":
                    raise httpx.HTTPStatusError(
                        UNSAFE_MESSAGE,
                        request=unsafe_request,
                        response=httpx.Response(429, request=unsafe_request, text=UNSAFE_BODY),
                    )
                return httpx.Response(403, text=UNSAFE_MESSAGE, headers={"X-Secret": SECRETS[0]})

            client = stack.enter_context(httpx.Client(transport=httpx.MockTransport(handler)))
            monkeypatch.setattr(
                "financial_research.research.live.SECProvider",
                lambda **kwargs: SECProvider(client=client, **kwargs),
            )
            monkeypatch.setattr(
                "financial_research.research.live.YahooMarketProvider",
                lambda **kwargs: YahooMarketProvider(client=client, **kwargs),
            )
            builder = LiveContextBuilder(
                ResearchConfig(sec_user_agent=SECRETS[2] + " contact@example.test")
            )
            llm = FakeLLMClient([])
            return ResearchAgent(registry=create_skill_registry(builder), llm=llm), llm, builder

        yield create


def events(caplog, name):
    formatter = OperationalFormatter()
    return [
        json.loads(formatter.format(record))
        for record in caplog.records
        if getattr(record, "event", "") == name
    ]


@pytest.mark.parametrize(
    "provider,operation,mode,exception_type,upstream_status",
    [
        ("sec-edgar", "fetch_company_tickers", "status", "HTTPStatusError", 403),
        ("sec-edgar", "fetch_companyfacts", "status", "HTTPStatusError", 403),
        ("sec-edgar", "fetch_submissions", "status", "HTTPStatusError", 403),
        ("sec-edgar", "fetch_submissions_archive", "status", "HTTPStatusError", 403),
        ("yahoo-chart", "fetch_market_history", "status", "HTTPStatusError", 403),
        ("sec-edgar", "fetch_company_tickers", "raw_status", "HTTPStatusError", 429),
        ("yahoo-chart", "fetch_market_history", "raw_status", "HTTPStatusError", 429),
        ("sec-edgar", "fetch_company_tickers", "timeout", "ReadTimeout", None),
        ("yahoo-chart", "fetch_market_history", "timeout", "ReadTimeout", None),
        ("yahoo-chart", "fetch_market_history", "chart", "ProviderError", None),
    ],
)
def test_provider_failure_is_safe_and_correlated_at_the_production_502_boundary(
    production_env,
    compiled_frontend,
    failing_agent,
    caplog,
    provider,
    operation,
    mode,
    exception_type,
    upstream_status,
):
    agent, llm, _ = failing_agent(operation, mode)
    app = create_production_app(frontend_dir=compiled_frontend, agent_factory=lambda: agent)
    with TestClient(app) as client, caplog.at_level(logging.INFO):
        response = client.post(REPORT, json=BODY, headers={**ACCESS, "X-Request-ID": SECRETS[0]})
    identifier = response.headers["X-Request-ID"]
    assert response.status_code == 502
    assert response.json() == {
        "error_code": "PROVIDER_ERROR",
        "message": "An external data provider request failed.",
        "request_id": identifier,
    }
    assert UUID(identifier).version == 4 and llm.call_count == 0
    [failure] = events(caplog, "provider_failure")
    assert failure["timestamp"]
    assert {key: failure[key] for key in ("level", "provider", "operation", "exception_type")} == {
        "level": "ERROR",
        "provider": provider,
        "operation": operation,
        "exception_type": exception_type,
    }
    expected_keys = {
        "timestamp",
        "level",
        "event",
        "request_id",
        "provider",
        "operation",
        "exception_type",
    }
    if upstream_status is not None:
        assert failure["upstream_status"] == upstream_status
        expected_keys.add("upstream_status")
    assert set(failure) == expected_keys
    [completed] = events(caplog, "http_request")
    assert failure["request_id"] == completed["request_id"] == identifier
    assert completed["status_code"] == 502 and completed["path"] == REPORT
    assert completed["method"] == "POST" and completed["duration_ms"] >= 0
    formatted = "\n".join(OperationalFormatter().format(record) for record in caplog.records)
    for secret in (*SECRETS, UNSAFE_URL, "SECRET", UNSAFE_HEADER, UNSAFE_BODY):
        assert secret not in formatted and secret not in response.text
    record = next(r for r in caplog.records if getattr(r, "event", "") == "provider_failure")
    assert record.exc_info is None and record.stack_info is None
    assert all(secret not in record.getMessage() for secret in SECRETS)
    assert not app.state.research_guard.busy
    assert provider_failure_state.get() is None


def test_later_request_cannot_reuse_previous_provider_diagnostics(
    production_env, compiled_frontend, failing_agent, caplog
):
    agent, _, _ = failing_agent("fetch_company_tickers")
    calls = 0

    def factory():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ProviderError(UNSAFE_MESSAGE)
        return agent

    app = create_production_app(frontend_dir=compiled_frontend, agent_factory=factory)
    with TestClient(app) as client, caplog.at_level(logging.INFO):
        first = client.post(REPORT, json=BODY, headers=ACCESS)
        second = client.post(REPORT, json=BODY, headers=ACCESS)
    first_event, second_event = events(caplog, "provider_failure")
    assert first.status_code == second.status_code == 502
    assert first_event["provider"] == "sec-edgar"
    assert second_event["provider"] == second_event["operation"] == "unknown"
    assert second_event["exception_type"] == "ProviderError"
    assert "upstream_status" not in second_event
    assert first_event["request_id"] != second_event["request_id"]
    assert second_event["request_id"] == second.headers["X-Request-ID"]


def test_plain_api_metadata_also_preserves_worker_diagnostics(failing_agent, caplog):
    agent, _, _ = failing_agent("fetch_companyfacts", "raw_status")
    with (
        TestClient(create_app(agent_factory=lambda: agent)) as client,
        caplog.at_level(logging.INFO),
    ):
        response = client.post(REPORT, json=BODY)
    [failure] = events(caplog, "provider_failure")
    assert response.status_code == 502
    assert (
        failure["request_id"] == response.json()["request_id"] == response.headers["X-Request-ID"]
    )
    assert failure["operation"] == "fetch_companyfacts" and failure["upstream_status"] == 429


def test_concurrent_requests_keep_separate_provider_diagnostics(caplog):
    barrier = Barrier(2)

    class Builder:
        def build(self, *, ticker, as_of_date):
            def fail(request):
                barrier.wait(timeout=5)
                raise httpx.ReadTimeout(UNSAFE_MESSAGE, request=request)

            with httpx.Client(transport=httpx.MockTransport(fail)) as client:
                provider = "sec-edgar" if ticker == "NVDA" else "yahoo-chart"
                operation = "fetch_company_tickers" if ticker == "NVDA" else "fetch_market_history"
                JsonTransport(provider, client=client).get(UNSAFE_URL, operation=operation)

    def factory():
        return ResearchAgent(registry=create_skill_registry(Builder()), llm=FakeLLMClient([]))

    with (
        TestClient(create_app(agent_factory=factory)) as client,
        ThreadPoolExecutor(max_workers=2) as pool,
        caplog.at_level(logging.INFO),
    ):
        pending = [
            pool.submit(client.post, REPORT, json={**BODY, "ticker": t}) for t in ("NVDA", "ACME")
        ]
        responses = [result.result(timeout=10) for result in pending]
    failures = {event["request_id"]: event for event in events(caplog, "provider_failure")}
    assert len(failures) == 2
    for response, provider in zip(responses, ("sec-edgar", "yahoo-chart"), strict=True):
        assert response.status_code == 502
        assert failures[response.headers["X-Request-ID"]]["provider"] == provider


def test_non_provider_errors_do_not_emit_provider_failure(
    production_env, compiled_frontend, caplog
):
    def factory():
        raise DataValidationError(UNSAFE_MESSAGE)

    app = create_production_app(frontend_dir=compiled_frontend, agent_factory=factory)
    with TestClient(app) as client, caplog.at_level(logging.INFO):
        response = client.post(REPORT, json=BODY, headers=ACCESS)
    assert response.status_code == 422 and response.json()["error_code"] == "DATA_VALIDATION_ERROR"
    assert events(caplog, "provider_failure") == []
    assert len(events(caplog, "http_request")) == 1
