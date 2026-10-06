"""Expose Stage 1 quality and objective ages without inventing a staleness rule."""

from financial_research.fundamentals.registry import METRIC_REGISTRY
from financial_research.schemas.research import ResearchContext
from financial_research.schemas.tools import CalculationParameter, ResearchQualityResult
from financial_research.tools.common import context_limitations, validate_context
from financial_research.tools.evidence import (
    computation,
    fundamental_evidence,
    market_evidence,
    unique_evidence,
)


def inspect_research_quality(context: ResearchContext) -> ResearchQualityResult:
    validate_context(context, allow_failed_quality=True)
    latest_market = context.market.observations[-1] if context.market.observations else None
    latest_fundamental = max(
        context.fundamentals.observations, key=lambda o: o.available_date, default=None
    )
    available = {o.metric for o in context.fundamentals.observations}
    evidence = []
    calculations = []
    if latest_market is not None:
        evidence.append(market_evidence(latest_market, context.market.metadata))
    if latest_fundamental is not None:
        evidence.append(fundamental_evidence(latest_fundamental))
    for reference, name, source_date in (
        (
            evidence[0] if latest_market else None,
            "market_age_calendar_days",
            latest_market.date if latest_market else None,
        ),
        (
            evidence[-1] if latest_fundamental else None,
            "fundamental_age_calendar_days",
            latest_fundamental.available_date if latest_fundamental else None,
        ),
    ):
        if reference is not None and source_date is not None:
            ref, calc = computation(
                name=name,
                metric=name,
                formula="(as_of_date - source_date).days",
                inputs=(reference,),
                value=(context.as_of_date - source_date).days,
                parameters=(
                    CalculationParameter(name="as_of_date", value=str(context.as_of_date)),
                ),
                session=context.as_of_date,
            )
            evidence.append(ref)
            calculations.append(calc)
    return ResearchQualityResult(
        ticker=context.ticker,
        as_of_date=context.as_of_date,
        quality=context.quality,
        overall_status=context.quality.status,
        issues=context.quality.issues,
        latest_market_session=latest_market.date if latest_market else None,
        market_age_calendar_days=(context.as_of_date - latest_market.date).days
        if latest_market
        else None,
        latest_fundamental_available_date=latest_fundamental.available_date
        if latest_fundamental
        else None,
        fundamental_age_calendar_days=(context.as_of_date - latest_fundamental.available_date).days
        if latest_fundamental
        else None,
        available_registered_metrics=tuple(m for m in METRIC_REGISTRY if m in available),
        missing_registered_metrics=tuple(m for m in METRIC_REGISTRY if m not in available),
        provenance_summary=context.provenance,
        evidence=unique_evidence(tuple(evidence)),
        calculation_provenance=tuple(calculations),
        limitations=context_limitations(context),
    )
