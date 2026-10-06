import math
from datetime import UTC, date, datetime, timedelta

import pytest

from financial_research.exceptions import DataValidationError
from financial_research.market.features import calculate_features
from financial_research.schemas.market import MarketBar


def bars(closes: list[float]) -> tuple[MarketBar, ...]:
    return tuple(
        MarketBar(
            ticker="ABC",
            date=date(2025, 1, 1) + timedelta(days=i),
            open=close,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=100,
            provider="fixture",
            retrieved_at=datetime(2025, 6, 1, tzinfo=UTC),
        )
        for i, close in enumerate(closes)
    )


def test_returns_and_relative_sma() -> None:
    features = calculate_features(bars([10, 11, 12, 13, 14]))
    assert features[0].simple_return is None
    assert features[0].log_return is None
    assert features[1].simple_return == pytest.approx(0.1)
    assert features[1].log_return == pytest.approx(math.log(1.1))
    assert features[3].close_to_sma_5 is None
    assert features[4].close_to_sma_5 == pytest.approx(14 / 12 - 1)


def test_volatility_sample_not_annualized_and_exact_warmup() -> None:
    closes = [100.0]
    expected_returns = [0.01 if i % 2 == 0 else -0.02 for i in range(60)]
    for change in expected_returns:
        closes.append(closes[-1] * (1 + change))
    features = calculate_features(bars(closes))
    assert features[19].rolling_volatility_20 is None
    assert features[20].rolling_volatility_20 == pytest.approx(0.015 * math.sqrt(20 / 19))
    assert features[59].rolling_volatility_60 is None
    assert features[60].rolling_volatility_60 == pytest.approx(0.015 * math.sqrt(60 / 59))
    assert features[19].close_to_sma_20 == pytest.approx(closes[19] / (sum(closes[:20]) / 20) - 1)
    assert features[59].close_to_sma_60 == pytest.approx(closes[59] / (sum(closes[:60]) / 60) - 1)


@pytest.mark.parametrize("invalid", ["duplicate", "unsorted", "nan"])
def test_invalid_feature_input(invalid: str) -> None:
    data = bars([10, 11])
    if invalid == "duplicate":
        data = (data[0], data[0])
    elif invalid == "unsorted":
        data = tuple(reversed(data))
    else:
        data = (data[0].model_copy(update={"close": float("nan")}),)
    with pytest.raises(DataValidationError):
        calculate_features(data)


def test_features_never_mix_securities() -> None:
    data = bars([10, 11])
    with pytest.raises(DataValidationError):
        calculate_features((data[0], data[1].model_copy(update={"ticker": "OTHER"})))
