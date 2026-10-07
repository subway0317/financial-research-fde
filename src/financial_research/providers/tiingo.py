"""Secure Tiingo EOD adapter with the frozen uniform OHLC transformation.

Daily UTC-midnight timestamps label sessions; they are never converted to local
dates. Volume is Tiingo's split-adjusted adjVolume, without further adjustment.
Reference metadata is local, explicit and separate from provider source data.
"""

import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import quote

import httpx
from pydantic import SecretStr

from financial_research.exceptions import ConfigurationError, DataValidationError, ProviderError
from financial_research.market_reference import (
    PRODUCT_CONTRACT_VERSION,
    PRODUCT_SCOPE,
    REGISTRY_HASH,
    REGISTRY_VERSION,
    resolve_exchange,
)
from financial_research.provider_diagnostics import ProviderOperation, capture_provider_failure
from financial_research.schemas.base import canonical_ticker
from financial_research.schemas.market import (
    MarketBar,
    MarketDataset,
    MarketMetadata,
    PriceAdjustmentPolicy,
)
from financial_research.schemas.provenance import ProvenanceRecord, SourceType

logger = logging.getLogger(__name__)
ADJUSTMENT_ABS_TOL = 1e-10
ADJUSTMENT_REL_TOL = 1e-10
PROVIDER = "tiingo-eod"
_DATE_LABEL = re.compile(r"\d{4}-\d{2}-\d{2}(?:T00:00:00(?:\.0{1,6})?(?:Z|\+00:00))?")


@dataclass(frozen=True)
class _Response:
    payload: object
    content_hash: str
    retrieved_at: datetime


class _TiingoTransport:
    """Dict/list transport isolated from SEC's existing dict-only contract."""

    def __init__(self, token: str, client: httpx.Client | None, timeout: float) -> None:
        self._token = SecretStr(token)
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=False)
        self._owns_client = client is None
        self._timeout = timeout

    def get(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        operation: ProviderOperation,
    ) -> _Response:
        logger.info("provider request provider=%s operation=%s", PROVIDER, operation)
        try:
            response = self._client.get(
                "https://api.tiingo.com" + path,
                params=params,
                headers={
                    "Authorization": "Token " + self._token.get_secret_value(),
                    "User-Agent": "financial-research-fde/0.1",
                },
                timeout=self._timeout,
                follow_redirects=False,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            capture_provider_failure(PROVIDER, operation, exc)
            # Suppress raw exception chaining in rendered tracebacks/public errors.
            raise ProviderError("tiingo-eod request failed") from None
        try:
            payload = response.json()
        except ValueError:
            raise DataValidationError("tiingo-eod returned invalid JSON") from None
        return _Response(payload, hashlib.sha256(response.content).hexdigest(), datetime.now(UTC))

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


def _number(value: object, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected a numeric field")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError("invalid numeric field")
    return number


def _volume(value: object) -> int:
    # Match MarketBar's strict integer policy; no float coercion or rounding.
    if type(value) is not int or value < 0:
        raise ValueError("expected nonnegative integer share volume")
    return value


def _session_date(value: object) -> date:
    if not isinstance(value, str) or _DATE_LABEL.fullmatch(value) is None:
        raise ValueError("invalid EOD session label")
    return date.fromisoformat(value[:10])


def _ohlc_valid(values: dict[str, float]) -> bool:
    return (
        values["low"] <= min(values["open"], values["close"])
        and values["high"] >= max(values["open"], values["close"])
        and values["high"] >= values["low"]
    )


class TiingoMarketProvider:
    def __init__(
        self, *, api_token: str, client: httpx.Client | None = None, timeout: float = 30
    ) -> None:
        token = api_token.strip()
        if not token or any(not 33 <= ord(char) <= 126 for char in token):
            raise ConfigurationError("TIINGO_API_TOKEN must be configured for Tiingo")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ConfigurationError("invalid Tiingo HTTP timeout")
        self._transport = _TiingoTransport(token, client, timeout)

    def close(self) -> None:
        self._transport.close()

    def get_market(self, ticker: str, start: date, end: date) -> MarketDataset:
        try:
            ticker = canonical_ticker(ticker)
            if type(start) is not date or type(end) is not date or start > end:
                raise ValueError("invalid market request range")
        except ValueError:
            raise DataValidationError("invalid Tiingo market request") from None
        path = f"/tiingo/daily/{quote(ticker.lower(), safe='')}"
        metadata = self._transport.get(path, operation="fetch_market_metadata")
        try:
            if not isinstance(metadata.payload, dict):
                raise ValueError("expected metadata object")
            if canonical_ticker(metadata.payload.get("ticker")) != ticker:
                raise ValueError("metadata ticker mismatch")
            exchange_code = metadata.payload.get("exchangeCode")
            reference = resolve_exchange(exchange_code)
        except (TypeError, ValueError):
            raise DataValidationError("Tiingo metadata failed canonical validation") from None

        prices = self._transport.get(
            path + "/prices",
            operation="fetch_market_history",
            params={
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "resampleFreq": "daily",
                "format": "json",
            },
        )
        try:
            if not isinstance(prices.payload, list) or not prices.payload:
                raise ValueError("expected nonempty prices array")
            bars: list[MarketBar] = []
            for row in prices.payload:
                if not isinstance(row, dict):
                    raise ValueError("expected price object")
                session = _session_date(row["date"])
                if not start <= session <= end:
                    raise ValueError("session outside requested range")
                if bars and session <= bars[-1].date:
                    raise ValueError("sessions must be strictly increasing and unique")
                raw = {f: _number(row[f], positive=True) for f in ("open", "high", "low", "close")}
                supplied = {f: _number(row["adj" + f.capitalize()], positive=True) for f in raw}
                _volume(row["volume"])
                volume = _volume(row["adjVolume"])
                _number(row["splitFactor"], positive=True)
                _number(row["divCash"])
                if not _ohlc_valid(raw) or not _ohlc_valid(supplied):
                    raise ValueError("invalid OHLC relation")
                factor = supplied["close"] / raw["close"]
                if not math.isfinite(factor) or factor <= 0:
                    raise ValueError("invalid adjustment factor")
                calculated = {f: raw[f] * factor for f in ("open", "high", "low")}
                if not all(
                    math.isclose(
                        calculated[f],
                        supplied[f],
                        abs_tol=ADJUSTMENT_ABS_TOL,
                        rel_tol=ADJUSTMENT_REL_TOL,
                    )
                    for f in calculated
                ):
                    raise ValueError("inconsistent adjusted OHLC basis")
                bars.append(
                    MarketBar(
                        ticker=ticker,
                        date=session,
                        open=calculated["open"],
                        high=calculated["high"],
                        low=calculated["low"],
                        close=supplied["close"],
                        volume=volume,
                        provider=PROVIDER,
                        retrieved_at=prices.retrieved_at,
                    )
                )
            manifest = {
                "provider": PROVIDER,
                "ticker": ticker,
                "requested_start": start.isoformat(),
                "requested_end": end.isoformat(),
                "price_response_sha256": prices.content_hash,
                "metadata_response_sha256": metadata.content_hash,
                "exchangeCode": exchange_code,
                "registry_version": REGISTRY_VERSION,
                "registry_sha256": REGISTRY_HASH,
                "product_contract": PRODUCT_CONTRACT_VERSION,
            }
            digest = hashlib.sha256(
                json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            provenance = ProvenanceRecord(
                provider=PROVIDER,
                source_type=SourceType.SOURCE_FACT,
                source_reference=f"tiingo-eod:{ticker}:{start.isoformat()}:{end.isoformat()}",
                retrieved_at=prices.retrieved_at,
                data_vintage=f"sha256:{digest}",
                content_hash=digest,
                transformation=(
                    "Tiingo prices: close=adjClose; O/H/L=raw*(adjClose/close)",
                    "Tiingo volume: adjVolume; split adjusted, not dividend-price scaled; "
                    "unchanged",
                    "Tiingo EOD date parsed as session-date label without timezone conversion",
                    f"Tiingo price response sha256={prices.content_hash}",
                    f"Tiingo metadata response sha256={metadata.content_hash}; "
                    f"exchangeCode={exchange_code}",
                    "retrieved_at records completion of Tiingo metadata/prices retrieval",
                    f"local reference registry={REGISTRY_VERSION}; sha256={REGISTRY_HASH}",
                    f"product contract={PRODUCT_CONTRACT_VERSION}; scope={PRODUCT_SCOPE}",
                    f"reference mapping: canonical_exchange={reference.canonical_exchange}; "
                    f"currency={reference.currency} (product contract); "
                    f"timezone={reference.timezone} "
                    "(exchange ET / IANA); currency/timezone are not Tiingo response fields",
                    "reference sources: " + "; ".join(reference.sources),
                    "retrieval-vintage adjustments; not an archived historical as-of price vintage",
                    "requested range preserved; observed sessions only; no independent calendar "
                    "completeness guarantee or synthesized sessions",
                ),
            )
            dataset = MarketDataset(
                observations=tuple(bars),
                metadata=MarketMetadata(
                    price_adjustment_policy=PriceAdjustmentPolicy.SPLIT_AND_DIVIDEND_ADJUSTED,
                    currency=reference.currency,
                    exchange_timezone=reference.timezone,
                    requested_start=start,
                    requested_end=end,
                    provenance=provenance,
                ),
            )
        except (KeyError, TypeError, ValueError, ArithmeticError):
            raise DataValidationError("Tiingo prices failed canonical normalization") from None
        logger.info(
            "market normalized provider=%s ticker=%s sessions=%d", PROVIDER, ticker, len(bars)
        )
        return dataset
