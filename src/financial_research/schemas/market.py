"""Canonical daily bars, registered features and adjustment policy."""

from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, Field, FiniteFloat, model_validator

from financial_research.schemas.base import CanonicalModel, NonEmpty, Ticker
from financial_research.schemas.provenance import ProvenanceRecord

PositivePrice = Annotated[FiniteFloat, Field(gt=0)]


class PriceAdjustmentPolicy(StrEnum):
    RAW = "RAW"
    SPLIT_ADJUSTED = "SPLIT_ADJUSTED"
    SPLIT_AND_DIVIDEND_ADJUSTED = "SPLIT_AND_DIVIDEND_ADJUSTED"


class MarketBar(CanonicalModel):
    ticker: Ticker
    date: date
    open: PositivePrice
    high: PositivePrice
    low: PositivePrice
    close: PositivePrice
    volume: Annotated[int, Field(ge=0, strict=True)]
    provider: NonEmpty
    retrieved_at: AwareDatetime

    @model_validator(mode="after")
    def valid_ohlc(self) -> "MarketBar":
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("invalid OHLC relationship")
        if self.low > self.high:
            raise ValueError("low exceeds high")
        return self


class MarketMetadata(CanonicalModel):
    price_adjustment_policy: PriceAdjustmentPolicy
    currency: NonEmpty
    exchange_timezone: NonEmpty
    requested_start: date
    requested_end: date
    provenance: ProvenanceRecord

    @model_validator(mode="after")
    def valid_range(self) -> "MarketMetadata":
        if self.requested_start > self.requested_end:
            raise ValueError("invalid market request range")
        return self


class MarketFeatureObservation(CanonicalModel):
    date: date
    simple_return: FiniteFloat | None = None
    log_return: FiniteFloat | None = None
    rolling_volatility_20: FiniteFloat | None = None
    rolling_volatility_60: FiniteFloat | None = None
    close_to_sma_5: FiniteFloat | None = None
    close_to_sma_20: FiniteFloat | None = None
    close_to_sma_60: FiniteFloat | None = None


class MarketDataset(CanonicalModel):
    observations: tuple[MarketBar, ...]
    metadata: MarketMetadata


class MarketResearch(MarketDataset):
    features: tuple[MarketFeatureObservation, ...]
    feature_provenance: ProvenanceRecord
