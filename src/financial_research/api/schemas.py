"""HTTP contracts only; tools remain independent of these request/envelope models."""

import re
from datetime import date
from typing import Annotated, Literal

from pydantic import UUID4, AwareDatetime, BeforeValidator, Field, model_validator

from financial_research.schemas.agent import GroundedResearchAnswer
from financial_research.schemas.base import CanonicalModel, NonEmpty, Ticker
from financial_research.schemas.quality import QualityReport
from financial_research.schemas.tools import ComparisonSpec, ToolResult


def _date_input(value: object) -> date:
    if type(value) is date:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return date.fromisoformat(value)
    raise ValueError("as_of_date must be an ISO calendar date YYYY-MM-DD")


class ResearchRequest(CanonicalModel):
    ticker: Ticker
    as_of_date: Annotated[date, BeforeValidator(_date_input)]


class AgentResearchRequest(ResearchRequest):
    question: Annotated[NonEmpty, Field(max_length=8000)]


class AgentResearchEnvelope(CanonicalModel):
    request_id: UUID4
    schema_version: Literal["1.0"] = "1.0"
    generated_at: AwareDatetime
    data: GroundedResearchAnswer
    quality: QualityReport
    limitations: tuple[str, ...]


class FundamentalTrendsRequest(ResearchRequest):
    metrics: Annotated[list[NonEmpty], Field(min_length=1, max_length=10)] | None = None

    @model_validator(mode="after")
    def unique_metrics(self) -> "FundamentalTrendsRequest":
        if self.metrics is not None and len(set(self.metrics)) != len(self.metrics):
            raise ValueError("metrics must be unique")
        return self


class ComparePeriodsRequest(ResearchRequest):
    metric: NonEmpty
    comparison: ComparisonSpec = ComparisonSpec.LATEST_VS_PRIOR_YEAR_COMPARABLE


class MarketBehaviorRequest(ResearchRequest):
    lookback_sessions: Annotated[int, Field(ge=2, le=504, strict=True)] = 60


class ResearchEnvelope[T: ToolResult](CanonicalModel):
    request_id: UUID4
    schema_version: Literal["1.0"] = "1.0"
    generated_at: AwareDatetime
    data: T
    quality: QualityReport
    limitations: tuple[str, ...]


class ErrorResponse(CanonicalModel):
    error_code: NonEmpty
    message: NonEmpty
    request_id: UUID4


class HealthResponse(CanonicalModel):
    status: Literal["ok"] = "ok"
    service: Literal["financial-research-fde"] = "financial-research-fde"
