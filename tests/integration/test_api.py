import logging
from datetime import date
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from financial_research.api.app import create_app
from financial_research.exceptions import (
    ConfigurationError,
    DataValidationError,
    InsufficientHistoryError,
    PITViolationError,
    ProviderError,
    UnknownTickerError,
)
from financial_research.schemas.research import ResearchContext
from financial_research.tools import ResearchTools


class FixedBuilder:
    def __init__(self, context):
        self.context = context
        self.requests = []

    def build(self, *, ticker: str, as_of_date: date) -> ResearchContext:
        self.requests.append((ticker, as_of_date))
        assert ticker == self.context.ticker
        assert as_of_date == self.context.as_of_date
        return self.context


@pytest.fixture
def api_client(fiscal_context):
    builder = FixedBuilder(fiscal_context)
    with TestClient(create_app(tools_factory=lambda: ResearchTools(builder))) as client:
        yield client, builder


@pytest.mark.parametrize(
    "endpoint,extra",
    [
        ("company-snapshot", {}),
        ("fundamental-trends", {"metrics": ["revenue", "operating_cash_flow"]}),
        ("compare-periods", {"metric": "revenue", "comparison": "latest_vs_prior_year_comparable"}),
        ("market-behavior", {"lookback_sessions": 20}),
        ("quality", {}),
    ],
)
def test_five_research_endpoints(api_client, endpoint, extra) -> None:
    client, builder = api_client
    response = client.post(
        f"/v1/research/{endpoint}", json={"ticker": " nvda ", "as_of_date": "2025-05-25", **extra}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert UUID(body["request_id"]).version == 4
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert body["schema_version"] == "1.0"
    assert body["data"]["ticker"] == "NVDA"
    assert body["data"]["as_of_date"] == "2025-05-25"
    assert body["quality"]["status"] == "PASS_WITH_WARNINGS"
    assert body["generated_at"]
    assert body["data"]["evidence"]
    assert builder.requests == [("NVDA", date(2025, 5, 25))]
    if endpoint == "fundamental-trends":
        rows = body["data"]["metrics"]
        assert rows[0]["percentage_change"] == "0.5"
        assert rows[1]["comparison_status"] == "UNAVAILABLE"
    if endpoint == "market-behavior":
        assert body["data"]["window"]["annualized"] is False
    assert "observations" not in body["data"]  # No public raw-context endpoint.


@pytest.mark.parametrize(
    "endpoint,extra",
    [
        ("fundamental-trends", {"metrics": ["EBITDA"]}),
        ("compare-periods", {"metric": "EBITDA"}),
    ],
)
def test_unsupported_metric_422_before_provider_access(api_client, endpoint, extra) -> None:
    client, builder = api_client
    response = client.post(
        f"/v1/research/{endpoint}", json={"ticker": "NVDA", "as_of_date": "2025-05-25", **extra}
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "UNSUPPORTED_METRIC"
    assert builder.requests == []


@pytest.mark.parametrize(
    "endpoint,body",
    [
        ("company-snapshot", {"ticker": "NVDA"}),
        ("company-snapshot", {"ticker": 123, "as_of_date": "2025-05-25"}),
        ("company-snapshot", {"ticker": "NVDA", "as_of_date": 0}),
        ("company-snapshot", {"ticker": "NVDA", "as_of_date": "2025-02-30"}),
        ("company-snapshot", {"ticker": "NVDA", "as_of_date": "2025-05-25T00:00:00Z"}),
        ("market-behavior", {"ticker": "NVDA", "as_of_date": "2025-05-25", "lookback_sessions": 1}),
        (
            "market-behavior",
            {"ticker": "NVDA", "as_of_date": "2025-05-25", "lookback_sessions": 505},
        ),
        (
            "market-behavior",
            {"ticker": "NVDA", "as_of_date": "2025-05-25", "lookback_sessions": "20"},
        ),
        (
            "market-behavior",
            {"ticker": "NVDA", "as_of_date": "2025-05-25", "lookback_sessions": True},
        ),
        ("fundamental-trends", {"ticker": "NVDA", "as_of_date": "2025-05-25", "metrics": []}),
        (
            "fundamental-trends",
            {"ticker": "NVDA", "as_of_date": "2025-05-25", "metrics": ["revenue", "revenue"]},
        ),
        (
            "compare-periods",
            {
                "ticker": "NVDA",
                "as_of_date": "2025-05-25",
                "metric": "revenue",
                "comparison": "latest_vs_previous_period",
            },
        ),
    ],
)
def test_typed_request_validation(api_client, endpoint, body) -> None:
    client, builder = api_client
    response = client.post(f"/v1/research/{endpoint}", json=body)
    assert response.status_code == 422
    assert response.json()["error_code"] == "REQUEST_VALIDATION_ERROR"
    assert UUID(response.json()["request_id"]).version == 4
    assert builder.requests == []


@pytest.mark.parametrize(
    "error,status,code",
    [
        (UnknownTickerError, 404, "UNKNOWN_TICKER"),
        (ProviderError, 502, "PROVIDER_ERROR"),
        (DataValidationError, 422, "DATA_VALIDATION_ERROR"),
        (InsufficientHistoryError, 422, "INSUFFICIENT_HISTORY"),
        (PITViolationError, 500, "PIT_VIOLATION"),
        (ConfigurationError, 503, "CONFIGURATION_ERROR"),
        (RuntimeError, 500, "INTERNAL_ERROR"),
    ],
)
def test_error_mapping_and_sanitization(error, status, code) -> None:
    class BrokenBuilder:
        def build(self, **kwargs):
            raise error("private-secret /tmp/private-path raw-provider-payload")

    with TestClient(
        create_app(tools_factory=lambda: ResearchTools(BrokenBuilder())),
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            "/v1/research/company-snapshot", json={"ticker": "NVDA", "as_of_date": "2025-05-25"}
        )
    assert response.status_code == status
    assert response.json()["error_code"] == code
    assert UUID(response.json()["request_id"]).version == 4
    assert response.headers["X-Request-ID"] == response.json()["request_id"]
    for forbidden in ("private-secret", "/tmp/", "raw-provider-payload", "Traceback"):
        assert forbidden not in response.text


def test_health_openapi_and_docs_never_construct_providers() -> None:
    def never():
        raise AssertionError("liveness and docs must not depend on provider configuration")

    with TestClient(create_app(tools_factory=never)) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "financial-research-fde"}
        assert client.get("/docs").status_code == 200
        schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) == {
        "/health",
        "/v1/agent/research",
        "/v1/reports/equity-research",
        *(
            f"/v1/research/{endpoint}"
            for endpoint in (
                "company-snapshot",
                "fundamental-trends",
                "compare-periods",
                "market-behavior",
                "quality",
            )
        ),
    }
    assert schema["components"]["schemas"]["TrendDirection"]["enum"] == [
        "INCREASED",
        "DECREASED",
        "UNCHANGED",
        "UNAVAILABLE",
    ]
    assert (
        schema["components"]["schemas"]["MarketBehaviorRequest"]["properties"]["lookback_sessions"][
            "maximum"
        ]
        == 504
    )


def test_request_ids_are_runtime_metadata_and_logs_are_correlated(api_client, caplog) -> None:
    client, builder = api_client
    caplog.set_level(logging.INFO)
    body = {"ticker": "NVDA", "as_of_date": "2025-05-25"}
    first = client.post("/v1/research/compare-periods", json={**body, "metric": "revenue"}).json()
    second = client.post("/v1/research/compare-periods", json={**body, "metric": "revenue"}).json()
    assert first["request_id"] != second["request_id"]
    assert first["data"] == second["data"]
    assert len(builder.requests) == 2
    message = next(
        record.message for record in caplog.records if record.message.startswith("research request")
    )
    assert all(
        field in message
        for field in (
            "request_id=",
            "endpoint=",
            "ticker=NVDA",
            "as_of_date=2025-05-25",
            "tool_name=compare_periods",
            "duration_ms=",
            "quality=",
        )
    )
