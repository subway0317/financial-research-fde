from datetime import UTC, date, datetime

import httpx
import pytest

from financial_research.company.service import CompanyService
from financial_research.exceptions import DataValidationError, ProviderError, UnknownTickerError
from financial_research.providers.market import YahooMarketProvider
from financial_research.providers.sec import SECProvider
from financial_research.schemas.market import PriceAdjustmentPolicy


def client_for(payload: object, status: int = 200) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json=payload))
    )


def chart_payload() -> dict:
    return {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {
                        "symbol": "ABC",
                        "currency": "USD",
                        "exchangeTimezoneName": "America/New_York",
                    },
                    "timestamp": [int(datetime(2025, 5, 23, 13, 30, tzinfo=UTC).timestamp())],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100],
                                "high": [110],
                                "low": [90],
                                "close": [100],
                                "volume": [1000],
                            }
                        ],
                        "adjclose": [{"adjclose": [50]}],
                    },
                }
            ],
        }
    }


def test_company_normalization_and_unknown_ticker() -> None:
    payload = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [[123, "ABC Corp", "ABC", "Nasdaq"]],
    }
    with client_for(payload) as client:
        provider = SECProvider(user_agent="Fixture fixture@example.com", client=client)
        assert CompanyService(provider).resolve(" abc ").cik == "0000000123"
        with pytest.raises(UnknownTickerError):
            provider.get_company("UNKNOWN")


def test_uniform_ohlc_adjustment_and_explicit_policy() -> None:
    with client_for(chart_payload()) as client:
        result = YahooMarketProvider(client=client).get_market(
            "ABC", date(2025, 5, 23), date(2025, 5, 25)
        )
    bar = result.observations[0]
    assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (50, 55, 45, 50, 1000)
    assert (
        result.metadata.price_adjustment_policy == PriceAdjustmentPolicy.SPLIT_AND_DIVIDEND_ADJUSTED
    )
    assert result.metadata.provenance.content_hash


@pytest.mark.parametrize("mutation", ["null", "length", "ohlc", "symbol", "duplicate", "future"])
def test_bad_market_payload_is_never_silently_repaired(mutation: str) -> None:
    payload = chart_payload()
    result = payload["chart"]["result"][0]
    quotes = result["indicators"]["quote"][0]
    if mutation == "null":
        quotes["open"][0] = None
    elif mutation == "length":
        quotes["volume"] = []
    elif mutation == "ohlc":
        quotes["high"][0] = 80
    elif mutation == "symbol":
        result["meta"]["symbol"] = "OTHER"
    elif mutation == "duplicate":
        result["timestamp"] *= 2
        for values in quotes.values():
            values *= 2
        result["indicators"]["adjclose"][0]["adjclose"] *= 2
    else:
        result["timestamp"][0] += 86400
    with client_for(payload) as client, pytest.raises(DataValidationError):
        YahooMarketProvider(client=client).get_market("ABC", date(2025, 5, 23), date(2025, 5, 23))


def test_provider_failures_have_stable_error_types() -> None:
    with client_for({}, 503) as client, pytest.raises(ProviderError):
        YahooMarketProvider(client=client).get_market("ABC", date(2025, 5, 1), date(2025, 5, 2))
    with pytest.raises(DataValidationError):
        SECProvider(user_agent="")


@pytest.mark.parametrize("mutation", ["chart_null", "overflow_timestamp", "bad_json"])
def test_malformed_response_has_validation_error(mutation: str) -> None:
    payload = chart_payload()
    if mutation == "chart_null":
        payload["chart"] = None
    elif mutation == "overflow_timestamp":
        payload["chart"]["result"][0]["timestamp"][0] = 10**30
    if mutation == "bad_json":
        client = httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"not JSON"))
        )
    else:
        client = client_for(payload)
    with client, pytest.raises(DataValidationError):
        YahooMarketProvider(client=client).get_market("ABC", date(2025, 5, 23), date(2025, 5, 23))
