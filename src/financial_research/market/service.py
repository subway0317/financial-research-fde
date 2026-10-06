"""Validated daily market capability with an interchangeable provider."""

from datetime import date

from pydantic import ValidationError

from financial_research.exceptions import DataValidationError, PITViolationError
from financial_research.market.features import FEATURE_DEFINITION, calculate_features
from financial_research.providers.base import MarketProvider
from financial_research.schemas.base import canonical_ticker
from financial_research.schemas.market import MarketDataset, MarketResearch
from financial_research.schemas.provenance import SourceType


class MarketService:
    def __init__(self, provider: MarketProvider) -> None:
        self._provider = provider

    def get(self, ticker: str, start: date, as_of_date: date) -> MarketResearch:
        try:
            ticker = canonical_ticker(ticker)
        except ValueError as exc:
            raise DataValidationError("invalid market ticker") from exc
        if start > as_of_date:
            raise DataValidationError("market start exceeds as_of_date")
        dataset = self._provider.get_market(ticker, start, as_of_date)
        try:
            dataset = MarketDataset.model_validate(dataset.model_dump())
        except ValidationError as exc:
            raise DataValidationError("invalid canonical market dataset") from exc
        if (
            dataset.metadata.requested_start != start
            or dataset.metadata.requested_end != as_of_date
        ):
            raise DataValidationError("market provider request coverage mismatch")
        for bar in dataset.observations:
            if bar.date > as_of_date:
                raise PITViolationError("market provider returned a future observation")
            if bar.date < start or bar.ticker != ticker:
                raise DataValidationError("market provider returned out-of-scope data")
        features = calculate_features(dataset.observations)
        return MarketResearch(
            observations=dataset.observations,
            metadata=dataset.metadata,
            features=features,
            feature_provenance=dataset.metadata.provenance.model_copy(
                update={
                    "source_type": SourceType.COMPUTED_RESULT,
                    "transformation": (
                        *dataset.metadata.provenance.transformation,
                        *FEATURE_DEFINITION,
                    ),
                }
            ),
        )
