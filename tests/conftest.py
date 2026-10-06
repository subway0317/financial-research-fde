"""The default suite is offline; live tests require explicit opt-in."""

import socket

import pytest


@pytest.fixture(autouse=True)
def block_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("live") is not None:
        return

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Network is forbidden in the offline test suite")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture
def provider_payloads() -> dict:
    import json
    from pathlib import Path

    root = Path(__file__).parent / "fixtures"
    return {
        "directory": json.loads((root / "sec_directory.json").read_text()),
        "market": json.loads((root / "yahoo_nvda.json").read_text()),
        "fundamentals": json.loads((root / "sec_nvda_companyfacts.json").read_text()),
        "expected": json.loads((root / "nvda_expected.json").read_text()),
    }


@pytest.fixture
def fixture_builder(provider_payloads: dict):
    import copy

    import httpx

    from financial_research.company.service import CompanyService
    from financial_research.fundamentals.service import FundamentalService
    from financial_research.market.service import MarketService
    from financial_research.providers.market import YahooMarketProvider
    from financial_research.providers.sec import SECProvider
    from financial_research.research import ResearchContextBuilder

    def sec_handler(request: httpx.Request) -> httpx.Response:
        assert "fixture@example.com" in request.headers["User-Agent"]
        if request.url.path.endswith("company_tickers_exchange.json"):
            data = provider_payloads["directory"]
        elif "/companyfacts/" in request.url.path:
            data = provider_payloads["fundamentals"]
        else:
            raise AssertionError(f"unexpected SEC request {request.url}")
        return httpx.Response(200, json=data)

    def market_handler(request: httpx.Request) -> httpx.Response:
        payload = copy.deepcopy(provider_payloads["market"])
        result = payload["chart"]["result"][0]
        lower, upper = int(request.url.params["period1"]), int(request.url.params["period2"])
        positions = [i for i, stamp in enumerate(result["timestamp"]) if lower <= stamp < upper]
        result["timestamp"] = [result["timestamp"][i] for i in positions]
        for key, values in result["indicators"]["quote"][0].items():
            result["indicators"]["quote"][0][key] = [values[i] for i in positions]
        adjusted = result["indicators"]["adjclose"][0]["adjclose"]
        result["indicators"]["adjclose"][0]["adjclose"] = [adjusted[i] for i in positions]
        return httpx.Response(200, json=payload)

    with (
        httpx.Client(transport=httpx.MockTransport(sec_handler)) as sec_client,
        httpx.Client(transport=httpx.MockTransport(market_handler)) as market_client,
    ):
        sec = SECProvider(user_agent="Fixture fixture@example.com", client=sec_client)
        market = YahooMarketProvider(client=market_client)
        yield ResearchContextBuilder(
            company_service=CompanyService(sec),
            market_service=MarketService(market),
            fundamental_service=FundamentalService(sec),
        )


@pytest.fixture
def nvda_context(fixture_builder):
    from datetime import date

    return fixture_builder.build(ticker="NVDA", as_of_date=date(2025, 5, 25))


@pytest.fixture
def fiscal_context(nvda_context):
    import json
    from pathlib import Path

    from financial_research.quality.checks import evaluate_quality
    from financial_research.schemas.fundamentals import FundamentalObservation, FundamentalResearch
    from financial_research.schemas.research import ResearchContext

    rows = json.loads((Path(__file__).parent / "fixtures/fiscal_observations.json").read_text())
    observations = tuple(FundamentalObservation.model_validate(row) for row in rows)
    fundamentals = FundamentalResearch(
        observations=observations, provenance=tuple(o.provenance_record() for o in observations)
    )
    quality = evaluate_quality(
        ticker=nvda_context.ticker,
        as_of_date=nvda_context.as_of_date,
        company=nvda_context.company,
        market=nvda_context.market,
        fundamentals=fundamentals,
    )
    return ResearchContext.model_validate(
        {
            **nvda_context.model_dump(),
            "fundamentals": fundamentals.model_dump(),
            "quality": quality.model_dump(),
            "provenance": (*nvda_context.provenance, *fundamentals.provenance),
        }
    )
