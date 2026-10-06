"""Opt-in real composite smoke; execution failure and provider blocks stay distinct."""

import argparse
import logging
import sys
from datetime import date

from financial_research.config import ResearchConfig
from financial_research.exceptions import ProviderError
from financial_research.research.live import LiveContextBuilder
from financial_research.schemas.base import CanonicalModel, Ticker
from financial_research.schemas.quality import QualityStatus
from financial_research.schemas.research import ResearchContext
from financial_research.schemas.skills import (
    ResearchEvidencePackage,
    SkillStatus,
    SynthesisReadiness,
    TraceAction,
)
from financial_research.skills.equity_research import EquityResearchSkill
from financial_research.tools.service import ContextBuilder
from financial_research.tools.smoke import SmokeStatus, provider_failure


class CompositeSmokeResult(CanonicalModel):
    status: SmokeStatus
    ticker: Ticker
    as_of_date: date
    provider_path: tuple[str, ...] = (
        "SEC directory",
        "Yahoo-compatible daily chart",
        "SEC companyfacts + submissions",
    )
    context_build_count: int
    subskills_executed: tuple[str, ...] = ()
    skill_status: SkillStatus
    synthesis_readiness: SynthesisReadiness
    quality_status: QualityStatus | None = None
    market_rows: int = 0
    fundamental_rows: int = 0
    evidence_count: int = 0
    calculation_count: int = 0
    evidence_integrity: bool = False
    limitations: tuple[str, ...] = ()
    error_code: str | None = None
    http_status: int | None = None
    provider_host: str | None = None


class CountingBuilder:
    def __init__(self, builder: ContextBuilder) -> None:
        self._builder = builder
        self.build_count = 0
        self.context: ResearchContext | None = None
        self.error: Exception | None = None

    def build(self, *, ticker: str, as_of_date: date) -> ResearchContext:
        self.build_count += 1
        try:
            self.context = self._builder.build(ticker=ticker, as_of_date=as_of_date)
        except Exception as exc:
            self.error = exc
            raise
        return self.context


def run_live_composite_smoke(
    *,
    ticker: str,
    as_of_date: date,
    config: ResearchConfig | None = None,
    builder: ContextBuilder | None = None,
) -> CompositeSmokeResult:
    counted = CountingBuilder(builder if builder is not None else LiveContextBuilder(config))
    package = EquityResearchSkill(counted).run(ticker=ticker, as_of_date=as_of_date)
    subskills = tuple(
        step.target
        for step in package.execution_trace.steps
        if step.action_type == TraceAction.SKILL_CALL and step.target != "equity_research"
    )
    status = SmokeStatus.PASS
    error_code = package.metadata.error.error_code if package.metadata.error else None
    http_status, provider_host = None, None
    integrity = False
    context = counted.context
    if package.metadata.status == SkillStatus.FAILED:
        status = SmokeStatus.FAILED
        if isinstance(counted.error, ProviderError):
            status, http_status, provider_host = provider_failure(counted.error)
    else:
        # Validate the actual package and context; no changing exact financial targets.
        try:
            ResearchEvidencePackage.model_validate(package.model_dump())
            if (
                context is None
                or counted.build_count != 1
                or context.ticker != package.metadata.ticker
                or not context.company.cik
                or not context.market.observations
                or any(bar.date > as_of_date for bar in context.market.observations)
                or any(
                    fact.available_date > as_of_date for fact in context.fundamentals.observations
                )
                or any(
                    section is None
                    for section in (
                        package.company_overview,
                        package.fundamental_analysis,
                        package.market_analysis,
                        package.research_quality,
                    )
                )
                or subskills
                != (
                    "company_overview",
                    "fundamental_analysis",
                    "market_analysis",
                    "research_quality_audit",
                )
            ):
                raise ValueError("composite smoke integration invariant")
            integrity = True
        except (ValueError, TypeError):
            status, error_code = SmokeStatus.FAILED, "SMOKE_INTEGRITY_FAILURE"
    return CompositeSmokeResult(
        status=status,
        ticker=package.metadata.ticker,
        as_of_date=as_of_date,
        context_build_count=counted.build_count,
        subskills_executed=subskills,
        skill_status=package.metadata.status,
        synthesis_readiness=package.synthesis_readiness,
        quality_status=package.metadata.quality.status if package.metadata.quality else None,
        market_rows=len(context.market.observations) if context else 0,
        fundamental_rows=len(context.fundamentals.observations) if context else 0,
        evidence_count=len(package.evidence_index),
        calculation_count=len(package.calculation_provenance),
        evidence_integrity=integrity,
        limitations=package.limitations,
        error_code=error_code,
        http_status=http_status,
        provider_host=provider_host,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", default="NVDA")
    parser.add_argument("--as-of-date", required=True, type=date.fromisoformat)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = run_live_composite_smoke(ticker=args.ticker, as_of_date=args.as_of_date)
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
