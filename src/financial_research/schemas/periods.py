"""Explicit fiscal period labels; absence is not an invitation to infer a quarter."""

from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from financial_research.schemas.base import CanonicalModel, NonEmpty


class PeriodFrequency(StrEnum):
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"


class FiscalPeriod(CanonicalModel):
    frequency: PeriodFrequency
    fiscal_year: Annotated[int, Field(ge=1, le=9999, strict=True)]
    fiscal_quarter: Annotated[int, Field(ge=1, le=4, strict=True)] | None = None
    source_reference: NonEmpty

    @model_validator(mode="after")
    def consistent_label(self) -> "FiscalPeriod":
        if (self.frequency == PeriodFrequency.QUARTERLY) != (self.fiscal_quarter is not None):
            raise ValueError("quarterly labels require a quarter; annual labels prohibit one")
        return self
