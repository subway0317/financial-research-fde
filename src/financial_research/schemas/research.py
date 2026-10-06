"""Versioned public research contract and normalized reproducibility content."""

import json
from datetime import date
from typing import Any, Literal

from pydantic import AwareDatetime, model_validator

from financial_research.schemas.base import CanonicalModel, Ticker
from financial_research.schemas.company import CompanyProfile
from financial_research.schemas.fundamentals import FundamentalResearch
from financial_research.schemas.market import MarketResearch
from financial_research.schemas.provenance import ProvenanceRecord
from financial_research.schemas.quality import QualityReport, QualityStatus, Severity


class ResearchContext(CanonicalModel):
    schema_version: Literal["1.0"] = "1.0"
    ticker: Ticker
    as_of_date: date
    generated_at: AwareDatetime
    company: CompanyProfile
    market: MarketResearch
    fundamentals: FundamentalResearch
    provenance: tuple[ProvenanceRecord, ...]
    quality: QualityReport

    def normalized_business_json(self) -> str:
        """Ignore only explicitly volatile acquisition/build metadata."""

        def normalize(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: normalize(item)
                    for key, item in value.items()
                    if key not in {"generated_at", "retrieved_at"}
                }
            if isinstance(value, list):
                return [normalize(item) for item in value]
            return value

        return json.dumps(
            normalize(self.model_dump(mode="json")), sort_keys=True, separators=(",", ":")
        )

    @model_validator(mode="after")
    def future_information_requires_fail(self) -> "ResearchContext":
        required = set()
        if any(bar.date > self.as_of_date for bar in self.market.observations):
            required.add("FUTURE_MARKET_DATA")
        if any(o.available_date > self.as_of_date for o in self.fundamentals.observations):
            required.add("PIT_VIOLATION")
        error_codes = {i.code for i in self.quality.issues if i.severity == Severity.ERROR}
        if required and (self.quality.status != QualityStatus.FAIL or not required <= error_codes):
            raise ValueError("future information requires FAIL with explicit PIT error issues")
        return self
