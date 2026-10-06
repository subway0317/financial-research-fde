"""Observed-session descriptive market calculations; no signals or predictions."""

from statistics import stdev

from financial_research.schemas.research import ResearchContext
from financial_research.schemas.tools import (
    CalculationParameter,
    CalculationProvenance,
    EvidenceReference,
    LatestMarketFeatures,
    MarketBehaviorResult,
    MarketWindowSummary,
    ResultStatus,
)
from financial_research.tools.common import context_limitations, validate_context, validate_lookback
from financial_research.tools.evidence import computation, market_evidence, unique_evidence


def summarize_market_behavior(
    context: ResearchContext, *, lookback_sessions: int = 60
) -> MarketBehaviorResult:
    validate_lookback(lookback_sessions)
    validate_context(context)
    window, evidence, calculations = summarize_window(context, lookback_sessions)
    latest_features, feature_evidence, feature_calcs = relative_sma_evidence(context)
    latest = context.market.observations[-1] if context.market.observations else None
    return MarketBehaviorResult(
        ticker=context.ticker,
        as_of_date=context.as_of_date,
        quality=context.quality,
        latest_market_session=latest.date if latest else None,
        latest_close=latest.close if latest else None,
        window=window,
        latest_market_features=latest_features,
        evidence=unique_evidence((*evidence, *feature_evidence)),
        calculation_provenance=(*calculations, *feature_calcs),
        limitations=(*context_limitations(context), *window.limitations),
    )


def summarize_window(
    context: ResearchContext, sessions: int
) -> tuple[MarketWindowSummary, tuple[EvidenceReference, ...], tuple[CalculationProvenance, ...]]:
    bars = context.market.observations[-sessions:]
    if len(bars) < sessions:
        return (
            MarketWindowSummary(
                lookback_sessions_requested=sessions,
                lookback_sessions_available=len(bars),
                status=ResultStatus.UNAVAILABLE,
                volatility_status=ResultStatus.UNAVAILABLE,
                limitations=("INSUFFICIENT_OBSERVED_SESSIONS",),
            ),
            (),
            (),
        )
    metadata = context.market.metadata
    closes = tuple(market_evidence(bar, metadata) for bar in bars)
    highs = tuple(market_evidence(bar, metadata, "high") for bar in bars)
    lows = tuple(market_evidence(bar, metadata, "low") for bar in bars)
    cumulative = bars[-1].close / bars[0].close - 1
    # Exclude the first bar's return from the preceding, out-of-window session.
    returns = [bars[i].close / bars[i - 1].close - 1 for i in range(1, len(bars))]
    volatility = stdev(returns) if len(returns) >= 2 else None
    high, low = max(bar.high for bar in bars), min(bar.low for bar in bars)
    evidence = list((*closes, *highs, *lows))
    calculations = []
    params = (CalculationParameter(name="lookback_sessions", value=sessions),)
    values = (
        (
            "cumulative_close_to_close_return",
            "last_close / first_close - 1",
            cumulative,
            (closes[0], closes[-1]),
        ),
        ("window_high", "max(window.high)", high, highs),
        ("window_low", "min(window.low)", low, lows),
    )
    for name, formula, value, inputs in values:
        ref, calc = computation(
            name=name,
            metric=name,
            formula=formula,
            inputs=inputs,
            value=value,
            parameters=params,
            session=bars[-1].date,
        )
        evidence.append(ref)
        calculations.append(calc)
    if volatility is not None:
        ref, calc = computation(
            name="realized_volatility_daily",
            metric="realized_volatility_daily",
            formula="sample_std(close[t]/close[t-1]-1); ddof=1; not annualized",
            inputs=closes,
            value=volatility,
            session=bars[-1].date,
            parameters=(
                *params,
                CalculationParameter(name="ddof", value=1),
                CalculationParameter(name="annualized", value=False),
            ),
        )
        evidence.append(ref)
        calculations.append(calc)
    return (
        MarketWindowSummary(
            lookback_sessions_requested=sessions,
            lookback_sessions_available=len(bars),
            status=ResultStatus.AVAILABLE,
            cumulative_return=cumulative,
            realized_volatility_daily=volatility,
            volatility_status=ResultStatus.AVAILABLE
            if volatility is not None
            else ResultStatus.UNAVAILABLE,
            window_high=high,
            window_low=low,
            limitations=("INSUFFICIENT_RETURN_HISTORY",) if volatility is None else (),
        ),
        tuple(evidence),
        tuple(calculations),
    )


def relative_sma_evidence(
    context: ResearchContext,
) -> tuple[LatestMarketFeatures, tuple[EvidenceReference, ...], tuple[CalculationProvenance, ...]]:
    latest = context.market.features[-1] if context.market.features else None
    values = LatestMarketFeatures(
        close_to_sma_5=latest.close_to_sma_5 if latest else None,
        close_to_sma_20=latest.close_to_sma_20 if latest else None,
        close_to_sma_60=latest.close_to_sma_60 if latest else None,
    )
    evidence: list[EvidenceReference] = []
    calculations = []
    for sessions in (5, 20, 60):
        value = getattr(values, f"close_to_sma_{sessions}")
        if value is None:
            continue
        bars = context.market.observations[-sessions:]
        inputs = tuple(market_evidence(bar, context.market.metadata) for bar in bars)
        ref, calc = computation(
            name=f"close_to_sma_{sessions}",
            metric=f"close_to_sma_{sessions}",
            formula="latest_close / mean(last k closes) - 1",
            inputs=inputs,
            value=value,
            parameters=(CalculationParameter(name="k", value=sessions),),
            session=bars[-1].date,
        )
        evidence.extend((*inputs, ref))
        calculations.append(calc)
    return values, unique_evidence(tuple(evidence)), tuple(calculations)
