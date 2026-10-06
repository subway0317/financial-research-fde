"""Transport-independent, typed research results and grounding references."""

import json
from datetime import date as Date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, FiniteFloat

from financial_research.fundamentals.registry import MetricKind
from financial_research.schemas.base import CanonicalModel, NonEmpty, Ticker
from financial_research.schemas.company import CompanyProfile
from financial_research.schemas.fundamentals import FundamentalObservation
from financial_research.schemas.provenance import ProvenanceRecord
from financial_research.schemas.quality import QualityIssue, QualityReport, QualityStatus


class EvidenceKind(StrEnum):
    SOURCE_FACT = "SOURCE_FACT"
    COMPUTATION = "COMPUTATION"


class ResultStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class ComparisonSpec(StrEnum):
    LATEST_VS_PRIOR_YEAR_COMPARABLE = "latest_vs_prior_year_comparable"


class ComparisonType(StrEnum):
    YEAR_OVER_YEAR = "YEAR_OVER_YEAR"


class PercentageChangeStatus(StrEnum):
    MEANINGFUL = "MEANINGFUL"
    NOT_MEANINGFUL = "NOT_MEANINGFUL"
    UNAVAILABLE = "UNAVAILABLE"


class TrendDirection(StrEnum):
    INCREASED = "INCREASED"
    DECREASED = "DECREASED"
    UNCHANGED = "UNCHANGED"
    UNAVAILABLE = "UNAVAILABLE"


class EvidenceReference(CanonicalModel):
    evidence_id: NonEmpty
    kind: EvidenceKind
    metric: NonEmpty
    provider: NonEmpty
    source_reference: NonEmpty
    date: Date | None = None
    period_start: Date | None = None
    period_end: Date | None = None
    filed_at: Date | None = None
    available_date: Date | None = None
    value: str | None = None
    unit: str | None = None
    data_vintage: str | None = None
    transformation: tuple[str, ...] = ()


class CalculationParameter(CanonicalModel):
    name: NonEmpty
    value: str | int | bool


class CalculationProvenance(CanonicalModel):
    evidence_id: NonEmpty
    calculation_name: NonEmpty
    formula: NonEmpty
    input_evidence_ids: tuple[NonEmpty, ...]
    parameters: tuple[CalculationParameter, ...] = ()


class ToolResult(CanonicalModel):
    ticker: Ticker
    as_of_date: Date
    quality: QualityReport
    evidence: tuple[EvidenceReference, ...] = ()
    calculation_provenance: tuple[CalculationProvenance, ...] = ()
    limitations: tuple[NonEmpty, ...] = ()

    def normalized_business_json(self) -> str:
        def normalize(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: normalize(item)
                    for key, item in value.items()
                    if key not in {"retrieved_at", "generated_at", "request_id"}
                }
            if isinstance(value, list):
                return [normalize(item) for item in value]
            return value

        return json.dumps(
            normalize(self.model_dump(mode="json")), sort_keys=True, separators=(",", ":")
        )


class LatestMarketFeatures(CanonicalModel):
    close_to_sma_5: FiniteFloat | None = None
    close_to_sma_20: FiniteFloat | None = None
    close_to_sma_60: FiniteFloat | None = None


class MarketWindowSummary(CanonicalModel):
    lookback_sessions_requested: Annotated[int, Field(ge=2, le=504, strict=True)]
    lookback_sessions_available: Annotated[int, Field(ge=0, strict=True)]
    status: ResultStatus
    cumulative_return: FiniteFloat | None = None
    realized_volatility_daily: FiniteFloat | None = None
    volatility_status: ResultStatus
    annualized: Literal[False] = False
    window_high: FiniteFloat | None = None
    window_low: FiniteFloat | None = None
    limitations: tuple[NonEmpty, ...] = ()


class MetricSnapshot(CanonicalModel):
    metric: NonEmpty
    metric_kind: MetricKind
    status: ResultStatus
    observation: FundamentalObservation | None = None
    limitations: tuple[NonEmpty, ...] = ()


class CompanySnapshotResult(ToolResult):
    company: CompanyProfile
    latest_market_session: Date | None = None
    latest_close: FiniteFloat | None = None
    market_windows: tuple[MarketWindowSummary, ...]
    latest_market_features: LatestMarketFeatures
    fundamentals: tuple[MetricSnapshot, ...]


class MetricTrendResult(CanonicalModel):
    metric: NonEmpty
    metric_kind: MetricKind
    current_observation: FundamentalObservation | None = None
    comparable_observation: FundamentalObservation | None = None
    comparison_type: ComparisonType = ComparisonType.YEAR_OVER_YEAR
    comparison_status: ResultStatus
    absolute_change: Annotated[Decimal, Field(allow_inf_nan=False)] | None = None
    percentage_change: Annotated[Decimal, Field(allow_inf_nan=False)] | None = None
    percentage_change_status: PercentageChangeStatus
    direction: TrendDirection
    evidence: tuple[EvidenceReference, ...] = ()
    calculation_provenance: tuple[CalculationProvenance, ...] = ()
    limitations: tuple[NonEmpty, ...] = ()


class FundamentalTrendResult(ToolResult):
    metrics: tuple[MetricTrendResult, ...]


class PeriodComparisonResult(ToolResult):
    comparison_spec: ComparisonSpec
    result: MetricTrendResult


class MarketBehaviorResult(ToolResult):
    latest_market_session: Date | None = None
    latest_close: FiniteFloat | None = None
    window: MarketWindowSummary
    latest_market_features: LatestMarketFeatures


class ResearchQualityResult(ToolResult):
    overall_status: QualityStatus
    issues: tuple[QualityIssue, ...]
    latest_market_session: Date | None = None
    market_age_calendar_days: Annotated[int, Field(ge=0)] | None = None
    latest_fundamental_available_date: Date | None = None
    fundamental_age_calendar_days: Annotated[int, Field(ge=0)] | None = None
    available_registered_metrics: tuple[str, ...]
    missing_registered_metrics: tuple[str, ...]
    provenance_summary: tuple[ProvenanceRecord, ...]
