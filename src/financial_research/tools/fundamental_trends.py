"""Composite tool reusing exactly the primitive comparison calculation."""

from financial_research.schemas.research import ResearchContext
from financial_research.schemas.tools import FundamentalTrendResult
from financial_research.tools.common import context_limitations, metric_names, validate_context
from financial_research.tools.evidence import unique_evidence
from financial_research.tools.period_comparison import compare_metric


def analyze_fundamental_trends(
    context: ResearchContext, *, metrics: list[str] | None = None
) -> FundamentalTrendResult:
    names = metric_names(metrics)
    validate_context(context)
    results = tuple(compare_metric(context, metric) for metric in names)
    return FundamentalTrendResult(
        ticker=context.ticker,
        as_of_date=context.as_of_date,
        quality=context.quality,
        metrics=results,
        evidence=unique_evidence(tuple(e for r in results for e in r.evidence)),
        calculation_provenance=tuple(c for r in results for c in r.calculation_provenance),
        limitations=tuple(
            dict.fromkeys(
                (
                    *context_limitations(context),
                    *(reason for r in results for reason in r.limitations),
                )
            )
        ),
    )
