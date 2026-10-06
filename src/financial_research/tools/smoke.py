"""Opt-in live integration, with external failures distinct from implementation failures."""

import argparse
import logging
import sys
from datetime import date
from enum import StrEnum

import httpx

from financial_research.config import ResearchConfig
from financial_research.exceptions import FinancialResearchError, ProviderError
from financial_research.research.live import LiveContextBuilder
from financial_research.schemas.base import CanonicalModel, Ticker
from financial_research.schemas.quality import QualityStatus
from financial_research.tools.company_snapshot import get_company_snapshot
from financial_research.tools.fundamental_trends import analyze_fundamental_trends


class SmokeStatus(StrEnum):
    PASS = "PASS"
    EXTERNAL_BLOCKED = "EXTERNAL BLOCKED"
    FAILED = "FAILED"


class LiveSmokeResult(CanonicalModel):
    status: SmokeStatus
    ticker: Ticker
    as_of_date: date
    provider_path: tuple[str, ...] = (
        "SEC directory",
        "Yahoo-compatible daily chart",
        "SEC companyfacts + submissions",
    )
    tools_exercised: tuple[str, ...] = ()
    market_rows: int = 0
    fundamental_rows: int = 0
    quality_status: QualityStatus | None = None
    completed_phase: str
    error_code: str | None = None
    http_status: int | None = None
    provider_host: str | None = None


def provider_failure(exc: ProviderError) -> tuple[SmokeStatus, int | None, str | None]:
    cause = exc.__cause__
    if isinstance(cause, httpx.HTTPStatusError):
        status = cause.response.status_code
        external = status in {401, 403, 408, 429, 500, 502, 503, 504}
        return (
            SmokeStatus.EXTERNAL_BLOCKED if external else SmokeStatus.FAILED,
            status,
            cause.request.url.host,
        )
    if isinstance(cause, httpx.TransportError):
        return SmokeStatus.EXTERNAL_BLOCKED, None, None
    return SmokeStatus.FAILED, None, None


def run_live_smoke(
    *, ticker: str, as_of_date: date, config: ResearchConfig | None = None
) -> LiveSmokeResult:
    completed = "none"
    exercised: list[str] = []
    context = None
    try:
        context = LiveContextBuilder(config).build(ticker=ticker, as_of_date=as_of_date)
        completed = "research_context"
        snapshot = get_company_snapshot(context)
        exercised.append("get_company_snapshot")
        completed = "company_snapshot"
        trends = analyze_fundamental_trends(context)
        exercised.append("analyze_fundamental_trends")
        completed = "fundamental_trends"
        # Schema, availability, and integration assertions; no brittle numeric targets.
        if (
            snapshot.ticker != context.ticker
            or not context.company.cik
            or not context.market.observations
            or any(b.date > as_of_date for b in context.market.observations)
            or any(o.available_date > as_of_date for o in context.fundamentals.observations)
            or not trends.metrics
        ):
            return LiveSmokeResult(
                status=SmokeStatus.FAILED,
                ticker=ticker,
                as_of_date=as_of_date,
                completed_phase=completed,
                tools_exercised=tuple(exercised),
                error_code="SMOKE_INTEGRITY_FAILURE",
            )
        return LiveSmokeResult(
            status=SmokeStatus.PASS,
            ticker=context.ticker,
            as_of_date=as_of_date,
            completed_phase=completed,
            tools_exercised=tuple(exercised),
            market_rows=len(context.market.observations),
            fundamental_rows=len(context.fundamentals.observations),
            quality_status=context.quality.status,
        )
    except ProviderError as exc:
        status, http_status, host = provider_failure(exc)
        return LiveSmokeResult(
            status=status,
            ticker=ticker,
            as_of_date=as_of_date,
            completed_phase=completed,
            tools_exercised=tuple(exercised),
            error_code="PROVIDER_ERROR",
            http_status=http_status,
            provider_host=host,
        )
    except FinancialResearchError as exc:
        return LiveSmokeResult(
            status=SmokeStatus.FAILED,
            ticker=ticker,
            as_of_date=as_of_date,
            completed_phase=completed,
            tools_exercised=tuple(exercised),
            error_code=type(exc).__name__,
        )
    except Exception as exc:
        return LiveSmokeResult(
            status=SmokeStatus.FAILED,
            ticker=ticker,
            as_of_date=as_of_date,
            completed_phase=completed,
            tools_exercised=tuple(exercised),
            error_code=f"IMPLEMENTATION_ERROR:{type(exc).__name__}",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", default="NVDA")
    parser.add_argument("--as-of-date", required=True, type=date.fromisoformat)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = run_live_smoke(ticker=args.ticker, as_of_date=args.as_of_date)
    sys.stdout.write(result.model_dump_json(indent=2) + "\n")
    sys.exit(
        0
        if result.status == SmokeStatus.PASS
        else 2
        if result.status == SmokeStatus.EXTERNAL_BLOCKED
        else 1
    )


if __name__ == "__main__":
    main()
