"""Small injected facade with ticker/as-of interfaces for API and future callers."""

import logging
import time
from datetime import date
from typing import Protocol

from financial_research.fundamentals.registry import require_metric
from financial_research.schemas.research import ResearchContext
from financial_research.schemas.tools import (
    CompanySnapshotResult,
    ComparisonSpec,
    FundamentalTrendResult,
    MarketBehaviorResult,
    PeriodComparisonResult,
    ResearchQualityResult,
)
from financial_research.tools.common import metric_names, validate_lookback
from financial_research.tools.company_snapshot import get_company_snapshot
from financial_research.tools.fundamental_trends import analyze_fundamental_trends
from financial_research.tools.market_behavior import summarize_market_behavior
from financial_research.tools.period_comparison import compare_periods
from financial_research.tools.research_quality import inspect_research_quality

logger = logging.getLogger(__name__)


class ContextBuilder(Protocol):
    def build(self, *, ticker: str, as_of_date: date) -> ResearchContext: ...


class ResearchTools:
    def __init__(self, builder: ContextBuilder) -> None:
        self._builder = builder

    def _context(self, ticker: str, as_of_date: date, tool_name: str) -> ResearchContext:
        start = time.perf_counter()
        context = self._builder.build(ticker=ticker, as_of_date=as_of_date)
        logger.info(
            "tool context tool_name=%s ticker=%s as_of_date=%s duration_ms=%.3f quality=%s",
            tool_name,
            context.ticker,
            as_of_date,
            (time.perf_counter() - start) * 1000,
            context.quality.status,
        )
        return context

    def get_company_snapshot(self, *, ticker: str, as_of_date: date) -> CompanySnapshotResult:
        return get_company_snapshot(self._context(ticker, as_of_date, "get_company_snapshot"))

    def analyze_fundamental_trends(
        self, *, ticker: str, as_of_date: date, metrics: list[str] | None = None
    ) -> FundamentalTrendResult:
        metric_names(metrics)
        return analyze_fundamental_trends(
            self._context(ticker, as_of_date, "analyze_fundamental_trends"), metrics=metrics
        )

    def compare_periods(
        self,
        *,
        ticker: str,
        as_of_date: date,
        metric: str,
        comparison: ComparisonSpec = ComparisonSpec.LATEST_VS_PRIOR_YEAR_COMPARABLE,
    ) -> PeriodComparisonResult:
        require_metric(metric)
        return compare_periods(
            self._context(ticker, as_of_date, "compare_periods"),
            metric=metric,
            comparison=comparison,
        )

    def summarize_market_behavior(
        self, *, ticker: str, as_of_date: date, lookback_sessions: int = 60
    ) -> MarketBehaviorResult:
        validate_lookback(lookback_sessions)
        return summarize_market_behavior(
            self._context(ticker, as_of_date, "summarize_market_behavior"),
            lookback_sessions=lookback_sessions,
        )

    def inspect_research_quality(self, *, ticker: str, as_of_date: date) -> ResearchQualityResult:
        return inspect_research_quality(
            self._context(ticker, as_of_date, "inspect_research_quality")
        )
