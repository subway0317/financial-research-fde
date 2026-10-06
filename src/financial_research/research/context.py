"""Orchestration of independent canonical capabilities; no raw source parsing."""

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from financial_research.company.service import CompanyService
from financial_research.config import ResearchConfig
from financial_research.fundamentals.pit import ObservedSessionCalendar, assert_pit_safe
from financial_research.fundamentals.service import FundamentalService
from financial_research.market.service import MarketService
from financial_research.quality.checks import evaluate_quality
from financial_research.schemas.provenance import ProvenanceRecord
from financial_research.schemas.research import ResearchContext

logger = logging.getLogger(__name__)


class ResearchContextBuilder:
    def __init__(
        self,
        *,
        company_service: CompanyService,
        market_service: MarketService,
        fundamental_service: FundamentalService,
        config: ResearchConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._company = company_service
        self._market = market_service
        self._fundamentals = fundamental_service
        self._config = config or ResearchConfig()
        self._clock = clock or (lambda: datetime.now(UTC))

    def build(self, *, ticker: str, as_of_date: date) -> ResearchContext:
        logger.info("context build ticker=%s as_of=%s", ticker, as_of_date)
        company = self._company.resolve(ticker)
        ticker = company.ticker
        market = self._market.get(
            ticker, as_of_date - timedelta(days=self._config.market_lookback_days), as_of_date
        )
        calendar = ObservedSessionCalendar(
            coverage_start=market.metadata.requested_start,
            coverage_end=as_of_date,
            sessions=tuple(bar.date for bar in market.observations),
        )
        fundamentals = self._fundamentals.get(company, as_of_date, calendar)
        assert_pit_safe(fundamentals.observations, as_of_date)
        quality = evaluate_quality(
            ticker=ticker,
            as_of_date=as_of_date,
            company=company,
            market=market,
            fundamentals=fundamentals,
            stale_market_days=self._config.stale_market_days,
        )
        provenance = _unique_provenance(
            (
                company.provenance,
                market.metadata.provenance,
                market.feature_provenance,
                *fundamentals.provenance,
            )
        )
        context = ResearchContext(
            ticker=ticker,
            as_of_date=as_of_date,
            generated_at=self._clock(),
            company=company,
            market=market,
            fundamentals=fundamentals,
            provenance=provenance,
            quality=quality,
        )
        logger.info(
            "context quality ticker=%s status=%s issues=%d",
            ticker,
            quality.status,
            len(quality.issues),
        )
        return context


def _unique_provenance(records: tuple[ProvenanceRecord, ...]) -> tuple[ProvenanceRecord, ...]:
    seen = set()
    result = []
    for record in records:
        key = record.model_dump_json(exclude={"retrieved_at"})
        if key not in seen:
            seen.add(key)
            result.append(record)
    return tuple(result)
