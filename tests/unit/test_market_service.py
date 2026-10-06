from datetime import date

import pytest

from financial_research.exceptions import DataValidationError, PITViolationError, ProviderError
from financial_research.market.service import MarketService
from financial_research.schemas.market import MarketDataset


class FixtureProvider:
    def __init__(self, dataset):
        self.dataset = dataset

    def get_market(self, ticker: str, start: date, end: date) -> MarketDataset:
        return self.dataset


def dataset(context):
    return MarketDataset(observations=context.market.observations, metadata=context.market.metadata)


@pytest.mark.parametrize("mutation", ["future", "duplicate", "ticker", "range", "nan"])
def test_provider_boundary_rejects_invalid_canonical_data(nvda_context, mutation) -> None:
    data = dataset(nvda_context)
    expected_error = DataValidationError
    if mutation == "range":
        data = data.model_copy(
            update={
                "metadata": data.metadata.model_copy(update={"requested_end": date(2025, 5, 26)})
            }
        )
    else:
        bars = data.observations
        if mutation == "future":
            updated = bars[-1].model_copy(update={"date": date(2025, 5, 26)})
            expected_error = PITViolationError
        elif mutation == "duplicate":
            updated = bars[-2]
        elif mutation == "ticker":
            updated = bars[-1].model_copy(update={"ticker": "OTHER"})
        else:
            updated = bars[-1].model_copy(update={"close": float("nan")})
        data = data.model_copy(update={"observations": (*bars[:-1], updated)})
    with pytest.raises(expected_error):
        MarketService(FixtureProvider(data)).get(
            "NVDA", data.metadata.requested_start, nvda_context.as_of_date
        )


def test_provider_failure_propagates(nvda_context) -> None:
    class BrokenProvider:
        def get_market(self, ticker: str, start: date, end: date) -> MarketDataset:
            raise ProviderError("fixture provider unavailable")

    with pytest.raises(ProviderError, match="unavailable"):
        MarketService(BrokenProvider()).get(
            "NVDA", nvda_context.market.metadata.requested_start, nvda_context.as_of_date
        )


def test_invalid_ticker_uses_domain_exception(nvda_context) -> None:
    with pytest.raises(DataValidationError):
        MarketService(FixtureProvider(dataset(nvda_context))).get(
            "bad ticker", nvda_context.market.metadata.requested_start, nvda_context.as_of_date
        )
