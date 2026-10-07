"""Thin typed transport routes; calculation and provider logic stay in tools/core."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from financial_research.api.dependencies import get_research_tools
from financial_research.api.responses import envelope
from financial_research.api.schemas import (
    ComparePeriodsRequest,
    ErrorResponse,
    FundamentalTrendsRequest,
    MarketBehaviorRequest,
    ResearchEnvelope,
    ResearchRequest,
)
from financial_research.public_research.schemas import (
    PublicCompanySnapshotResult,
    PublicFundamentalTrendResult,
    PublicMarketBehaviorResult,
    PublicPeriodComparisonResult,
    PublicResearchQualityResult,
    PublicToolResult,
)
from financial_research.tools.service import ResearchTools

responses: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse} for status in (404, 422, 500, 502, 503)
}
router = APIRouter(prefix="/v1/research", tags=["research"], responses=responses)
Tools = Annotated[ResearchTools, Depends(get_research_tools)]


@router.post("/company-snapshot", response_model=ResearchEnvelope[PublicCompanySnapshotResult])
def company_snapshot(
    body: ResearchRequest, request: Request, tools: Tools
) -> ResearchEnvelope[PublicToolResult]:
    return envelope(
        request,
        tools.get_company_snapshot(ticker=body.ticker, as_of_date=body.as_of_date),
        "get_company_snapshot",
    )


@router.post("/fundamental-trends", response_model=ResearchEnvelope[PublicFundamentalTrendResult])
def fundamental_trends(
    body: FundamentalTrendsRequest, request: Request, tools: Tools
) -> ResearchEnvelope[PublicToolResult]:
    return envelope(
        request,
        tools.analyze_fundamental_trends(
            ticker=body.ticker, as_of_date=body.as_of_date, metrics=body.metrics
        ),
        "analyze_fundamental_trends",
    )


@router.post("/compare-periods", response_model=ResearchEnvelope[PublicPeriodComparisonResult])
def period_comparison(
    body: ComparePeriodsRequest, request: Request, tools: Tools
) -> ResearchEnvelope[PublicToolResult]:
    return envelope(
        request,
        tools.compare_periods(
            ticker=body.ticker,
            as_of_date=body.as_of_date,
            metric=body.metric,
            comparison=body.comparison,
        ),
        "compare_periods",
    )


@router.post("/market-behavior", response_model=ResearchEnvelope[PublicMarketBehaviorResult])
def market_behavior(
    body: MarketBehaviorRequest, request: Request, tools: Tools
) -> ResearchEnvelope[PublicToolResult]:
    return envelope(
        request,
        tools.summarize_market_behavior(
            ticker=body.ticker, as_of_date=body.as_of_date, lookback_sessions=body.lookback_sessions
        ),
        "summarize_market_behavior",
    )


@router.post("/quality", response_model=ResearchEnvelope[PublicResearchQualityResult])
def research_quality(
    body: ResearchRequest, request: Request, tools: Tools
) -> ResearchEnvelope[PublicToolResult]:
    return envelope(
        request,
        tools.inspect_research_quality(ticker=body.ticker, as_of_date=body.as_of_date),
        "inspect_research_quality",
    )
