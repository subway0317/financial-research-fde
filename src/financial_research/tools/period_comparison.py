"""Primitive one-metric comparison; the selection engine is shared with trends."""

from decimal import localcontext

from financial_research.exceptions import DataValidationError
from financial_research.fundamentals.registry import require_metric
from financial_research.schemas.research import ResearchContext
from financial_research.schemas.tools import (
    CalculationProvenance,
    ComparisonSpec,
    MetricTrendResult,
    PercentageChangeStatus,
    PeriodComparisonResult,
    ResultStatus,
    TrendDirection,
)
from financial_research.tools.common import context_limitations, validate_context
from financial_research.tools.comparison import select_comparable_pair
from financial_research.tools.evidence import computation, fundamental_evidence


def compare_metric(context: ResearchContext, metric: str) -> MetricTrendResult:
    definition = require_metric(metric)
    pair = select_comparable_pair(context.fundamentals.observations, metric, context.as_of_date)
    sources = tuple(fundamental_evidence(o) for o in (pair.current, pair.prior) if o is not None)
    if pair.current is None or pair.prior is None:
        return MetricTrendResult(
            metric=metric,
            metric_kind=definition.metric_kind,
            current_observation=pair.current,
            comparison_status=ResultStatus.UNAVAILABLE,
            percentage_change_status=PercentageChangeStatus.UNAVAILABLE,
            direction=TrendDirection.UNAVAILABLE,
            evidence=sources,
            limitations=(pair.reason or "NO_COMPARABLE_PRIOR_PERIOD",),
        )
    current, prior = pair.current.value, pair.prior.value
    # Exact subtraction for arbitrary finite decimals, 50+ digits for ratio division.
    with localcontext() as arithmetic:
        arithmetic.prec = max(
            50,
            max(current.adjusted(), prior.adjusted())
            - min(int(current.as_tuple().exponent), int(prior.as_tuple().exponent))
            + 2,
        )
        absolute = current - prior
        percentage = absolute / prior if prior > 0 else None
    direction = (
        TrendDirection.INCREASED
        if absolute > 0
        else TrendDirection.DECREASED
        if absolute < 0
        else TrendDirection.UNCHANGED
    )
    absolute_ref, absolute_calc = computation(
        name="absolute_change",
        metric=metric,
        formula="current - prior",
        inputs=sources,
        value=absolute,
        session=pair.current.period_end,
    )
    evidence = (*sources, absolute_ref)
    calculations: tuple[CalculationProvenance, ...] = (absolute_calc,)
    limitations: tuple[str, ...] = ()
    if percentage is not None:
        percentage_ref, percentage_calc = computation(
            name="year_over_year_change",
            metric=metric,
            formula="(current - prior) / prior",
            inputs=sources,
            value=percentage,
            session=pair.current.period_end,
        )
        evidence = (*evidence, percentage_ref)
        calculations = (*calculations, percentage_calc)
    else:
        limitations = ("ZERO_PRIOR_BASE" if prior == 0 else "NEGATIVE_PRIOR_BASE",)
    return MetricTrendResult(
        metric=metric,
        metric_kind=definition.metric_kind,
        current_observation=pair.current,
        comparable_observation=pair.prior,
        comparison_status=ResultStatus.AVAILABLE,
        absolute_change=absolute,
        percentage_change=percentage,
        percentage_change_status=PercentageChangeStatus.MEANINGFUL
        if percentage is not None
        else PercentageChangeStatus.NOT_MEANINGFUL,
        direction=direction,
        evidence=evidence,
        calculation_provenance=calculations,
        limitations=limitations,
    )


def compare_periods(
    context: ResearchContext,
    *,
    metric: str,
    comparison: ComparisonSpec = ComparisonSpec.LATEST_VS_PRIOR_YEAR_COMPARABLE,
) -> PeriodComparisonResult:
    if comparison != ComparisonSpec.LATEST_VS_PRIOR_YEAR_COMPARABLE:
        raise DataValidationError("unsupported comparison specification")
    validate_context(context)
    result = compare_metric(context, metric)
    return PeriodComparisonResult(
        ticker=context.ticker,
        as_of_date=context.as_of_date,
        quality=context.quality,
        comparison_spec=comparison,
        result=result,
        evidence=result.evidence,
        calculation_provenance=result.calculation_provenance,
        limitations=(*context_limitations(context), *result.limitations),
    )
