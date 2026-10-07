"""Explicit selection and resource ownership, without external provider calls."""

import json
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from financial_research.config import ResearchConfig
from financial_research.exceptions import ConfigurationError, ProviderError
from financial_research.research.live import LiveContextBuilder, create_market_provider

SENTINEL = "__TIINGO_SECRET_SENTINEL__"


@pytest.mark.parametrize("provider", ["yahoo", "tiingo"])
def test_explicit_selection_never_uses_app_env_to_choose_provider(monkeypatch, provider):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MARKET_DATA_PROVIDER", provider)
    monkeypatch.setenv("TIINGO_API_TOKEN", SENTINEL)
    constructed = []
    monkeypatch.setattr(
        "financial_research.research.live.YahooMarketProvider",
        lambda **kw: constructed.append(("yahoo", kw)),
    )
    monkeypatch.setattr(
        "financial_research.research.live.TiingoMarketProvider",
        lambda **kw: constructed.append(("tiingo", kw)),
    )
    config = ResearchConfig.from_env()
    create_market_provider(config)
    assert [name for name, _ in constructed] == [provider]
    assert SENTINEL not in repr(config) + config.model_dump_json()
    if provider == "tiingo":
        assert constructed[0][1]["api_token"] == SENTINEL


def test_yahoo_is_development_default_without_tiingo_secret(monkeypatch):
    monkeypatch.delenv("MARKET_DATA_PROVIDER", raising=False)
    monkeypatch.delenv("TIINGO_API_TOKEN", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    config = ResearchConfig.from_env()
    assert config.market_data_provider == "yahoo" and config.tiingo_api_token is None
    provider = create_market_provider(config)
    provider.close()


@pytest.mark.parametrize("token", [None, SecretStr(""), SecretStr(" ")])
def test_tiingo_missing_token_fails_before_sec_construction(monkeypatch, token):
    def forbidden(**kwargs):
        raise AssertionError("missing config must not construct another provider")

    monkeypatch.setattr("financial_research.research.live.SECProvider", forbidden)
    monkeypatch.setattr("financial_research.research.live.YahooMarketProvider", forbidden)
    config = ResearchConfig(
        sec_user_agent="Test test@example.test",
        market_data_provider="tiingo",
        tiingo_api_token=token,
    )
    with pytest.raises(ConfigurationError, match="TIINGO_API_TOKEN"):
        LiveContextBuilder(config).build(ticker="NVDA", as_of_date=date(2026, 6, 30))


@pytest.mark.parametrize("value", ["unknown", "marketstack", "TIINGO", ""])
def test_invalid_provider_rejected_without_echoing_config(monkeypatch, value):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", value)
    monkeypatch.setenv("TIINGO_API_TOKEN", SENTINEL)
    with pytest.raises(ConfigurationError) as error:
        ResearchConfig.from_env()
    assert SENTINEL not in str(error.value)
    if value:
        assert value not in str(error.value)
    with pytest.raises(ValidationError):
        ResearchConfig(market_data_provider=value)


def test_live_composition_730_day_range_lifecycle_and_no_fallback(monkeypatch, nvda_context):
    from financial_research.research import live

    calls = []

    class Provider:
        def __init__(self, name):
            self.name = name

        def close(self):
            calls.append((self.name, "close"))

    market, sec = Provider("tiingo"), Provider("sec")
    monkeypatch.setattr(live, "TiingoMarketProvider", lambda **kwargs: market)
    monkeypatch.setattr(live, "SECProvider", lambda **kwargs: sec)

    def forbidden(**kwargs):
        raise AssertionError("Yahoo fallback is forbidden")

    monkeypatch.setattr(live, "YahooMarketProvider", forbidden)

    class Builder:
        def __init__(self, **kwargs):
            calls.append(("config", kwargs["config"].market_lookback_days))
            assert kwargs["market_service"]._provider is market

        def build(self, **kwargs):
            raise ProviderError("synthetic Tiingo failure")

    monkeypatch.setattr(live, "ResearchContextBuilder", Builder)
    config = ResearchConfig(
        sec_user_agent="Test test@example.test",
        market_data_provider="tiingo",
        tiingo_api_token=SecretStr(SENTINEL),
    )
    with pytest.raises(ProviderError):
        LiveContextBuilder(config).build(ticker="NVDA", as_of_date=nvda_context.as_of_date)
    assert ("config", 730) in calls
    assert ("sec", "close") in calls and ("tiingo", "close") in calls


def test_sec_constructor_failure_still_closes_market_client(monkeypatch):
    from financial_research.research import live

    closed = []

    class Market:
        def close(self):
            closed.append(True)

    monkeypatch.setattr(live, "TiingoMarketProvider", lambda **kwargs: Market())

    def fail(**kwargs):
        raise ConfigurationError("invalid SEC configuration")

    monkeypatch.setattr(live, "SECProvider", fail)
    config = ResearchConfig(
        sec_user_agent="test", market_data_provider="tiingo", tiingo_api_token=SecretStr(SENTINEL)
    )
    with pytest.raises(ConfigurationError):
        LiveContextBuilder(config).build(ticker="NVDA", as_of_date=date(2026, 6, 30))
    assert closed == [True]


def test_real_live_composition_uses_tiingo_observed_sessions_for_existing_pit(
    monkeypatch, provider_payloads
):
    from financial_research.providers.sec import SECProvider
    from financial_research.providers.tiingo import TiingoMarketProvider
    from financial_research.research import live

    sample = json.loads((Path(__file__).parents[1] / "fixtures/tiingo/nvda_730.json").read_text())
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "api.tiingo.com":
            payload = (
                sample["prices"] if request.url.path.endswith("/prices") else sample["metadata"]
            )
        elif request.url.path.endswith("company_tickers_exchange.json"):
            payload = provider_payloads["directory"]
        elif "/companyfacts/" in request.url.path:
            payload = provider_payloads["fundamentals"]
        else:
            assert request.url.path == "/submissions/CIK0001045810.json"
            payload = {
                "cik": "1045810",
                "filings": {
                    "recent": {
                        key: [] for key in ("accessionNumber", "reportDate", "filingDate", "form")
                    },
                    "files": [],
                },
            }
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(live, "SECProvider", lambda **kw: SECProvider(client=client, **kw))
        monkeypatch.setattr(
            live, "TiingoMarketProvider", lambda **kw: TiingoMarketProvider(client=client, **kw)
        )
        config = ResearchConfig(
            sec_user_agent="Fixture fixture@example.test",
            market_data_provider="tiingo",
            tiingo_api_token=SecretStr(SENTINEL),
        )
        end = date(2026, 6, 30)
        context = LiveContextBuilder(config).build(ticker="NVDA", as_of_date=end)
        repeated = LiveContextBuilder(config).build(ticker="NVDA", as_of_date=end)
        assert context.normalized_business_json() == repeated.normalized_business_json()
        assert not client.is_closed
    assert context.market.metadata.requested_start == end - timedelta(days=730)
    sessions = [bar.date for bar in context.market.observations]
    assert len(sessions) == 501 and context.market.observations[0].provider == "tiingo-eod"
    assert context.fundamentals.observations
    for observation in context.fundamentals.observations:
        assert observation.available_date == min(s for s in sessions if s > observation.filed_at)
        assert observation.available_date <= end
    assert all(request.url.host != "query1.finance.yahoo.com" for request in requests)
