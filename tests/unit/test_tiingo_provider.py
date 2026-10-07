"""Offline semantic regressions and rejection/security boundaries for Tiingo."""

import json
import logging
import traceback
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import fmean, stdev
from zoneinfo import ZoneInfo

import httpx
import pytest

from financial_research.exceptions import ConfigurationError, DataValidationError, ProviderError
from financial_research.market.features import calculate_features
from financial_research.market.service import MarketService
from financial_research.market_reference import (
    EXCHANGE_REGISTRY,
    REGISTRY_HASH,
    REGISTRY_VERSION,
    resolve_exchange,
)
from financial_research.provider_diagnostics import ProviderFailureState, provider_failure_state
from financial_research.providers.tiingo import TiingoMarketProvider

SENTINEL = "__TIINGO_SECRET_SENTINEL__"
FIXTURES = Path(__file__).parents[1] / "fixtures" / "tiingo"
DAY = date(2026, 9, 21)
META = {"ticker": "NVDA", "exchangeCode": "NASDAQ"}
ROW = {
    "date": "2026-09-21T00:00:00.000Z",
    "open": 100,
    "high": 110,
    "low": 90,
    "close": 100,
    "volume": 1000,
    "adjOpen": 50,
    "adjHigh": 55,
    "adjLow": 45,
    "adjClose": 50,
    "adjVolume": 2000,
    "splitFactor": 1,
    "divCash": 0,
}


def mock_client(metadata, prices, requests=None):
    def handle(request):
        if requests is not None:
            requests.append(request)
        payload = prices if request.url.path.endswith("/prices") else metadata
        # Also exercise Python's JSON NaN/Infinity acceptance, then canonical rejection.
        return httpx.Response(200, content=json.dumps(payload).encode())

    return httpx.Client(transport=httpx.MockTransport(handle))


def sample(name, ticker, start, end):
    payload = json.loads((FIXTURES / (name + ".json")).read_text())
    with mock_client(payload["metadata"], payload["prices"]) as client:
        provider = TiingoMarketProvider(api_token=SENTINEL, client=client)
        dataset = provider.get_market(ticker, start, end)
    return payload, dataset


def test_candidate_b_session_label_auth_and_truthful_metadata(caplog):
    requests = []
    with mock_client(META, [ROW], requests) as client, caplog.at_level(logging.INFO):
        provider = TiingoMarketProvider(api_token=SENTINEL, client=client, timeout=2.5)
        result = provider.get_market(" nvda ", DAY, DAY)
        provider.close()
        assert not client.is_closed  # injected clients remain caller-owned
    bar = result.observations[0]
    assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (50, 55, 45, 50, 2000)
    assert bar.date == DAY  # converting UTC midnight to New York would give Sep 20
    assert bar.provider == "tiingo-eod"
    assert result.metadata.price_adjustment_policy == "SPLIT_AND_DIVIDEND_ADJUSTED"
    assert (result.metadata.currency, result.metadata.exchange_timezone) == (
        "USD",
        "America/New_York",
    )
    assert len(requests) == 2
    assert requests[0].url.path == "/tiingo/daily/nvda"
    assert requests[1].url.path == "/tiingo/daily/nvda/prices"
    assert dict(requests[1].url.params) == {
        "startDate": str(DAY),
        "endDate": str(DAY),
        "resampleFreq": "daily",
        "format": "json",
    }
    for request in requests:
        assert request.headers["Authorization"] == "Token " + SENTINEL
        assert SENTINEL not in str(request.url) and "token" not in request.url.params
        assert request.extensions["timeout"]["read"] == 2.5
    provenance = result.metadata.provenance
    transformations = " ".join(provenance.transformation)
    assert "product contract" in transformations and "not Tiingo response fields" in transformations
    assert REGISTRY_VERSION in transformations and REGISTRY_HASH in transformations
    assert "exchangeCode=NASDAQ" in transformations
    assert (
        "price response sha256=" in transformations
        and "metadata response sha256=" in transformations
    )
    assert "retrieval-vintage" in transformations
    assert provenance.source_reference == "tiingo-eod:NVDA:2026-09-21:2026-09-21"
    assert SENTINEL not in result.model_dump_json() + caplog.text
    assert "Authorization" not in result.model_dump_json() + caplog.text


@pytest.mark.parametrize(
    "code,identity", [("NASDAQ", "The Nasdaq Stock Market"), ("NYSE", "New York Stock Exchange")]
)
def test_supported_reference_registry_and_provider(code, identity):
    entry = resolve_exchange(code)
    assert entry.supported and entry.canonical_exchange == identity
    assert entry.currency == "USD" and entry.timezone == "America/New_York"
    assert entry.sources and len(REGISTRY_HASH) == 64
    with mock_client({**META, "exchangeCode": code}, [ROW]) as client:
        assert (
            TiingoMarketProvider(api_token=SENTINEL, client=client)
            .get_market("NVDA", DAY, DAY)
            .metadata.currency
            == "USD"
        )
    assert set(EXCHANGE_REGISTRY) == {"NASDAQ", "NYSE"}
    with pytest.raises(TypeError):
        EXCHANGE_REGISTRY["UNKNOWN"] = entry


@pytest.mark.parametrize("code", [None, "", " ", 1, [], {}, "UNKNOWN", "nasdaq", "NYSEARCA", "IEX"])
def test_unknown_missing_malformed_exchange_fails_before_price_request(code):
    with pytest.raises(DataValidationError):
        resolve_exchange(code)
    requests = []
    with mock_client({**META, "exchangeCode": code}, [ROW], requests) as client:
        with pytest.raises(DataValidationError):
            TiingoMarketProvider(api_token=SENTINEL, client=client).get_market("NVDA", DAY, DAY)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "metadata",
    [
        [],
        None,
        {},
        {"ticker": "OTHER", "exchangeCode": "NASDAQ"},
        {"ticker": "NVDA"},
        {"ticker": 1, "exchangeCode": "NASDAQ"},
    ],
)
def test_bad_metadata(metadata):
    with mock_client(metadata, [ROW]) as client, pytest.raises(DataValidationError):
        TiingoMarketProvider(api_token=SENTINEL, client=client).get_market("NVDA", DAY, DAY)


@pytest.mark.parametrize(
    "day,hours",
    [
        (date(2026, 1, 15), -5),
        (date(2026, 7, 15), -4),
        (date(2026, 3, 6), -5),
        (date(2026, 3, 9), -4),
    ],
)
def test_reference_timezone_supports_dst(day, hours):
    zone = ZoneInfo(resolve_exchange("NASDAQ").timezone)
    noon = datetime.combine(day, datetime.min.time(), zone) + timedelta(hours=12)
    assert noon.utcoffset() == timedelta(hours=hours)
    # The spring transition skips directly from 01:59 EST to 03:00 EDT.
    before = datetime(2026, 3, 8, 6, 59, tzinfo=UTC).astimezone(zone)
    after = datetime(2026, 3, 8, 7, 0, tzinfo=UTC).astimezone(zone)
    assert (before.hour, after.hour) == (1, 3)


def test_forward_split_nflx_preserves_economic_return_and_share_basis():
    payload, dataset = sample("nflx_split", "NFLX", date(2025, 11, 10), date(2025, 11, 21))
    for row, bar in zip(payload["prices"], dataset.observations, strict=True):
        before = bar.date < date(2025, 11, 17)
        assert bar.close / row["close"] == pytest.approx(0.1 if before else 1)
        assert bar.volume == row["volume"] * (10 if before else 1)
    event = next(
        f for f in calculate_features(dataset.observations) if f.date == date(2025, 11, 17)
    )
    assert event.simple_return == pytest.approx(-0.008335056690973452)


def test_reverse_split_tlry_removes_artificial_jump_without_double_adjustment():
    payload, dataset = sample("tlry_reverse", "TLRY", date(2025, 11, 26), date(2025, 12, 5))
    for row, bar in zip(payload["prices"], dataset.observations, strict=True):
        before = bar.date < date(2025, 12, 2)
        assert bar.close / row["close"] == pytest.approx(10 if before else 1)
        assert bar.volume == row["adjVolume"]
        assert abs(bar.volume - row["volume"] / (10 if before else 1)) < 1
    event = next(f for f in calculate_features(dataset.observations) if f.date == date(2025, 12, 2))
    assert event.simple_return == pytest.approx(-0.014570552147239264)


def test_dividend_aapl_adjusts_prices_without_scaling_volume():
    payload, dataset = sample("aapl_dividend", "AAPL", date(2026, 8, 3), date(2026, 8, 21))
    event = date(2026, 8, 10)
    for row, bar in zip(payload["prices"], dataset.observations, strict=True):
        if bar.date < event:
            assert 0 < bar.close / row["close"] < 1
        else:
            assert bar.close == row["close"]
        assert bar.volume == row["volume"] == row["adjVolume"]
    assert next(r for r in payload["prices"] if r["date"].startswith(str(event)))["divCash"] > 0


def test_nvda_730_day_fixture_completeness_and_frozen_features():
    payload = json.loads((FIXTURES / "nvda_730.json").read_text())
    start, end = date(2024, 6, 30), date(2026, 6, 30)
    with mock_client(payload["metadata"], payload["prices"]) as client:
        market = MarketService(TiingoMarketProvider(api_token=SENTINEL, client=client)).get(
            "NVDA", start, end
        )
    assert len(market.observations) == 501  # this fixture only, not a universal adapter rule
    dates = [b.date for b in market.observations]
    assert dates == sorted(set(dates))
    assert dates[0] == date(2024, 7, 1) and dates[-1] == end
    assert (market.metadata.requested_start, market.metadata.requested_end) == (start, end)
    assert all(
        b.volume == r["volume"] for b, r in zip(market.observations, payload["prices"], strict=True)
    )
    assert sum(r["divCash"] > 0 for r in payload["prices"]) == 8
    closes = [b.close for b in market.observations]
    returns = [b / a - 1 for a, b in zip(closes[:-1], closes[1:], strict=True)]
    latest = market.features[-1]
    assert latest.rolling_volatility_20 == pytest.approx(stdev(returns[-20:]))
    assert latest.close_to_sma_60 == pytest.approx(closes[-1] / fmean(closes[-60:]) - 1)
    assert market.features[0].simple_return is None


@pytest.mark.parametrize("field", list(ROW))
def test_missing_required_field_is_rejected(field):
    row = {k: v for k, v in ROW.items() if k != field}
    with mock_client(META, [row]) as client, pytest.raises(DataValidationError):
        TiingoMarketProvider(api_token=SENTINEL, client=client).get_market("NVDA", DAY, DAY)


@pytest.mark.parametrize(
    "field,value",
    [
        ("adjVolume", 1.5),
        ("adjVolume", 1000.0),
        ("adjVolume", True),
        ("adjVolume", -1),
        ("volume", None),
        ("volume", 1.0),
        ("volume", -1),
        ("volume", False),
        ("close", 0),
        ("close", -1),
        ("close", True),
        ("close", "100"),
        ("close", float("nan")),
        ("adjClose", float("inf")),
        ("open", None),
        ("high", 90),
        ("low", 101),
        ("adjHigh", 40),
        ("adjOpen", 50.01),
        ("adjLow", float("nan")),
        ("splitFactor", 0),
        ("divCash", float("inf")),
        ("date", "2026-09-22T00:00:00.000Z"),
        ("date", "2026-09-20"),
        ("date", "2026-02-30T00:00:00.000Z"),
        ("date", "2026-09-21T13:00:00Z"),
        ("date", "2026-09-21T00:00:00-04:00"),
        ("date", None),
    ],
)
def test_invalid_price_fields_never_get_repaired(field, value):
    with mock_client(META, [{**ROW, field: value}]) as client, pytest.raises(DataValidationError):
        TiingoMarketProvider(api_token=SENTINEL, client=client).get_market("NVDA", DAY, DAY)


@pytest.mark.parametrize(
    "prices", [[], {}, None, [None], ["bad"], [ROW, ROW], [{**ROW, "date": "2026-09-22"}, ROW]]
)
def test_invalid_array_and_date_order(prices):
    with mock_client(META, prices) as client, pytest.raises(DataValidationError):
        TiingoMarketProvider(api_token=SENTINEL, client=client).get_market(
            "NVDA", DAY, DAY + timedelta(days=1)
        )


def test_fewer_observed_sessions_are_accepted_without_calendar_synthesis():
    with mock_client(META, [ROW]) as client:
        result = TiingoMarketProvider(api_token=SENTINEL, client=client).get_market(
            "NVDA", DAY - timedelta(days=730), DAY
        )
    assert len(result.observations) == 1
    assert "no independent calendar" in " ".join(result.metadata.provenance.transformation)


@pytest.mark.parametrize(
    "operation,status",
    [
        (operation, status)
        for operation in ("fetch_market_metadata", "fetch_market_history")
        for status in (401, 403, 429, 500)
    ],
)
def test_http_failures_capture_only_safe_diagnostics(operation, status, caplog):
    requests = []

    def handle(request):
        requests.append(request)
        current = (
            "fetch_market_history"
            if request.url.path.endswith("/prices")
            else "fetch_market_metadata"
        )
        return (
            httpx.Response(status, text=SENTINEL)
            if current == operation
            else httpx.Response(200, json=META)
        )

    state = ProviderFailureState()
    context = provider_failure_state.set(state)
    try:
        with (
            httpx.Client(transport=httpx.MockTransport(handle)) as client,
            caplog.at_level(logging.INFO),
        ):
            with pytest.raises(ProviderError) as error:
                TiingoMarketProvider(api_token=SENTINEL, client=client).get_market("NVDA", DAY, DAY)
        assert state.failure.provider == "tiingo-eod"
        assert state.failure.operation == operation and state.failure.upstream_status == status
        assert state.failure.exception_type == "HTTPStatusError"
        public = "".join(traceback.format_exception(error.value))
        assert SENTINEL not in public + repr(state) + caplog.text
        assert "Authorization" not in public + repr(state) + caplog.text
        assert len(requests) == (2 if operation == "fetch_market_history" else 1)
    finally:
        provider_failure_state.reset(context)


@pytest.mark.parametrize("mode", ["timeout", "bad_json", "redirect"])
def test_transport_errors_and_redirect_do_not_expose_or_forward_credentials(mode, caplog):
    requests = []

    def handle(request):
        requests.append(request)
        if mode == "timeout":
            raise httpx.ReadTimeout(SENTINEL, request=request)
        if mode == "redirect":
            return httpx.Response(302, headers={"Location": "https://other.example.test/"})
        return httpx.Response(200, text=SENTINEL)

    with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        with (
            caplog.at_level(logging.INFO),
            pytest.raises(DataValidationError if mode == "bad_json" else ProviderError) as error,
        ):
            TiingoMarketProvider(api_token=SENTINEL, client=client).get_market("NVDA", DAY, DAY)
    assert len(requests) == 1
    assert SENTINEL not in "".join(traceback.format_exception(error.value)) + caplog.text


def test_content_vintage_is_deterministic_and_sensitive_to_source_and_registry(monkeypatch):
    import financial_research.providers.tiingo as adapter

    def get(row=ROW):
        with mock_client(META, [row]) as client:
            return TiingoMarketProvider(api_token=SENTINEL, client=client).get_market(
                "NVDA", DAY, DAY
            )

    first, second = get(), get()
    assert first.metadata.provenance.content_hash == second.metadata.provenance.content_hash
    assert first.metadata.provenance.transformation == second.metadata.provenance.transformation
    assert first.metadata.provenance.retrieved_at != second.metadata.provenance.retrieved_at
    changed = get({**ROW, "adjVolume": ROW["adjVolume"] + 1})
    assert changed.metadata.provenance.content_hash != first.metadata.provenance.content_hash
    monkeypatch.setattr(adapter, "REGISTRY_HASH", "changed-reference-vintage")
    assert get().metadata.provenance.content_hash != first.metadata.provenance.content_hash


@pytest.mark.parametrize(
    "ticker,start,end", [("bad ticker", DAY, DAY), ("NVDA", DAY, DAY - timedelta(days=1))]
)
def test_invalid_input_makes_no_requests(ticker, start, end):
    requests = []
    with mock_client(META, [ROW], requests) as client, pytest.raises(DataValidationError):
        TiingoMarketProvider(api_token=SENTINEL, client=client).get_market(ticker, start, end)
    assert not requests


@pytest.mark.parametrize("token", ["", " ", "bad\nheader"])
def test_missing_or_malformed_secret_is_a_configuration_error(token):
    with pytest.raises(ConfigurationError):
        TiingoMarketProvider(api_token=token)


def test_owned_client_is_closed():
    provider = TiingoMarketProvider(api_token=SENTINEL)
    provider.close()
    assert provider._transport._client.is_closed
