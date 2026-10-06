"""Replaceable Yahoo-compatible daily chart adapter.

OHLC uses adjclose/close for every price. Volume remains reported share volume.
The resulting policy is explicitly split and dividend adjusted, never mixed OHLC.
"""

import logging
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from financial_research.exceptions import DataValidationError, ProviderError
from financial_research.providers.http import JsonTransport
from financial_research.schemas.base import canonical_ticker
from financial_research.schemas.market import (
    MarketBar,
    MarketDataset,
    MarketMetadata,
    PriceAdjustmentPolicy,
)

logger = logging.getLogger(__name__)


class YahooMarketProvider:
    def __init__(self, *, client: httpx.Client | None = None, timeout: float = 30) -> None:
        self._transport = JsonTransport("yahoo-chart", client=client, timeout=timeout)

    def close(self) -> None:
        self._transport.close()

    def get_market(self, ticker: str, start: date, end: date) -> MarketDataset:
        try:
            ticker = canonical_ticker(ticker)
        except ValueError as exc:
            raise DataValidationError("invalid market ticker") from exc
        if start > end:
            raise DataValidationError("market start exceeds end")
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker, safe='')}"
        response = self._transport.get(
            url,
            params={
                "period1": int(datetime.combine(start, time.min, UTC).timestamp()),
                "period2": int(
                    datetime.combine(end + timedelta(days=1), time.min, UTC).timestamp()
                ),
                "interval": "1d",
                "events": "div,splits",
            },
        )
        try:
            chart = response.payload["chart"]
            if not isinstance(chart, dict):
                raise ValueError("chart must be an object")
            if chart.get("error") is not None:
                raise ProviderError(f"Yahoo chart reported an error for {ticker}")
            results = chart["result"]
            if not isinstance(results, list) or len(results) != 1:
                raise ValueError("expected one chart result")
            result = results[0]
            meta = result["meta"]
            if canonical_ticker(meta["symbol"]) != ticker:
                raise ValueError("provider symbol mismatch")
            timezone = ZoneInfo(meta["exchangeTimezoneName"])
            timestamps = result["timestamp"]
            quotes = result["indicators"]["quote"][0]
            adjusted = result["indicators"]["adjclose"][0]["adjclose"]
            columns = [quotes[k] for k in ("open", "high", "low", "close", "volume")]
            if any(len(column) != len(timestamps) for column in [*columns, adjusted]):
                raise ValueError("chart column lengths differ")
            bars = []
            for index, stamp in enumerate(timestamps):
                session = datetime.fromtimestamp(stamp, UTC).astimezone(timezone).date()
                if not start <= session <= end:
                    raise ValueError("market observation outside requested range")
                close = quotes["close"][index]
                adjclose = adjusted[index]
                if close is None or adjclose is None or close <= 0 or adjclose <= 0:
                    raise ValueError("missing or nonpositive price/adjusted price")
                factor = adjclose / close
                bars.append(
                    MarketBar(
                        ticker=ticker,
                        date=session,
                        open=quotes["open"][index] * factor,
                        high=quotes["high"][index] * factor,
                        low=quotes["low"][index] * factor,
                        close=adjclose,
                        volume=quotes["volume"][index],
                        provider="yahoo-chart",
                        retrieved_at=response.provenance.retrieved_at,
                    )
                )
            dates = [bar.date for bar in bars]
            if dates != sorted(set(dates)):
                raise ValueError("market dates must be strictly increasing and unique")
            dataset = MarketDataset(
                observations=tuple(bars),
                metadata=MarketMetadata(
                    price_adjustment_policy=PriceAdjustmentPolicy.SPLIT_AND_DIVIDEND_ADJUSTED,
                    currency=meta["currency"],
                    exchange_timezone=meta["exchangeTimezoneName"],
                    requested_start=start,
                    requested_end=end,
                    provenance=response.provenance.model_copy(
                        update={
                            "transformation": (
                                "all OHLC multiplied by adjclose/close; reported volume unchanged",
                                "timestamp converted to exchange-local session date",
                            )
                        }
                    ),
                ),
            )
        except (KeyError, IndexError, TypeError, ValueError, ArithmeticError, OSError) as exc:
            raise DataValidationError("Yahoo chart failed canonical normalization") from exc
        logger.info("market normalized ticker=%s sessions=%d", ticker, len(bars))
        return dataset
