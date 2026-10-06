"""Frozen feature semantics: simple-return sample volatility, no annualization."""

import math
from statistics import fmean, stdev

from pydantic import ValidationError

from financial_research.exceptions import DataValidationError
from financial_research.schemas.market import MarketBar, MarketFeatureObservation

FEATURE_DEFINITION = (
    "simple_return=close[t]/close[t-1]-1",
    "log_return=log(close[t]/close[t-1])",
    "rolling_volatility_20/60=sample std(simple returns); ddof=1; not annualized",
    "close_to_sma_5/20/60=close/mean(last k closes)-1",
    "windows count observed sessions; unavailable warm-up results are null",
)


def calculate_features(bars: tuple[MarketBar, ...]) -> tuple[MarketFeatureObservation, ...]:
    if len({bar.ticker for bar in bars}) > 1:
        raise DataValidationError("feature input must contain one ticker")
    dates = [bar.date for bar in bars]
    if dates != sorted(set(dates)):
        raise DataValidationError("feature input dates must be strictly increasing and unique")
    try:
        for bar in bars:
            MarketBar.model_validate(bar.model_dump())
        closes = [bar.close for bar in bars]
        returns: list[float] = []
        features = []
        for index, bar in enumerate(bars):
            simple = closes[index] / closes[index - 1] - 1 if index else None
            logarithmic = math.log(closes[index] / closes[index - 1]) if index else None
            if simple is not None:
                if not math.isfinite(simple):
                    raise ValueError("nonfinite simple return")
                returns.append(simple)

            features.append(
                MarketFeatureObservation(
                    date=bar.date,
                    simple_return=simple,
                    log_return=logarithmic,
                    rolling_volatility_20=_volatility(returns, 20),
                    rolling_volatility_60=_volatility(returns, 60),
                    close_to_sma_5=_relative_sma(closes[: index + 1], 5),
                    close_to_sma_20=_relative_sma(closes[: index + 1], 20),
                    close_to_sma_60=_relative_sma(closes[: index + 1], 60),
                )
            )
    except (ValidationError, ArithmeticError, ValueError) as exc:
        raise DataValidationError("market feature computation failed validation") from exc
    return tuple(features)


def _volatility(returns: list[float], window: int) -> float | None:
    return stdev(returns[-window:]) if len(returns) >= window else None


def _relative_sma(closes: list[float], window: int) -> float | None:
    return closes[-1] / fmean(closes[-window:]) - 1 if len(closes) >= window else None
