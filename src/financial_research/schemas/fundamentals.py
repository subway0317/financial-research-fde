"""Financial period, filing date and availability are independent fields."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import AwareDatetime, Field, model_validator

from financial_research.schemas.base import CanonicalModel, NonEmpty, Ticker
from financial_research.schemas.periods import FiscalPeriod, PeriodFrequency
from financial_research.schemas.provenance import ProvenanceRecord, SourceType
from financial_research.schemas.quality import QualityIssue


class SourceFundamentalFact(CanonicalModel):
    ticker: Ticker
    metric: NonEmpty
    value: Annotated[Decimal, Field(allow_inf_nan=False)]
    unit: NonEmpty
    period_start: date | None = None
    period_end: date
    filed_at: date
    form: NonEmpty
    accession_number: NonEmpty
    provider: NonEmpty
    source_reference: NonEmpty
    retrieved_at: AwareDatetime
    data_vintage: NonEmpty
    transformation: tuple[str, ...] = ()
    fiscal_period: FiscalPeriod | None = None

    @model_validator(mode="after")
    def valid_chronology(self) -> "SourceFundamentalFact":
        if self.period_start is not None and self.period_start > self.period_end:
            raise ValueError("period_start exceeds period_end")
        if self.period_end > self.filed_at:
            raise ValueError("period_end exceeds filed_at")
        if self.fiscal_period is not None and self.period_start is not None:
            duration = (self.period_end - self.period_start).days + 1
            bounds = (
                (70, 110)
                if self.fiscal_period.frequency == PeriodFrequency.QUARTERLY
                else (330, 400)
            )
            if not bounds[0] <= duration <= bounds[1]:
                raise ValueError(
                    "fiscal period frequency contradicts duration; stubs/YTD unsupported"
                )
        return self

    def provenance_record(self) -> ProvenanceRecord:
        return ProvenanceRecord(
            provider=self.provider,
            source_type=SourceType.SOURCE_FACT,
            source_reference=self.source_reference,
            retrieved_at=self.retrieved_at,
            data_vintage=self.data_vintage,
            transformation=self.transformation,
        )


class FundamentalObservation(SourceFundamentalFact):
    available_date: date

    @model_validator(mode="after")
    def valid_availability(self) -> "FundamentalObservation":
        if self.available_date <= self.filed_at:
            raise ValueError("availability must be strictly after filing calendar date")
        return self


class FundamentalSourceDataset(CanonicalModel):
    facts: tuple[SourceFundamentalFact, ...]
    provenance: ProvenanceRecord
    issues: tuple[QualityIssue, ...] = ()


class FundamentalResearch(CanonicalModel):
    observations: tuple[FundamentalObservation, ...]
    provenance: tuple[ProvenanceRecord, ...]
    issues: tuple[QualityIssue, ...] = ()
