"""Latest legally available identity, market state and registered source facts."""

from financial_research.fundamentals.registry import METRIC_REGISTRY
from financial_research.schemas.research import ResearchContext
from financial_research.schemas.tools import (
    CalculationProvenance,
    CompanySnapshotResult,
    MetricSnapshot,
    ResultStatus,
)
from financial_research.tools.common import context_limitations, validate_context
from financial_research.tools.comparison import latest_observation
from financial_research.tools.evidence import fundamental_evidence, market_evidence, unique_evidence
from financial_research.tools.market_behavior import relative_sma_evidence, summarize_window


def get_company_snapshot(context: ResearchContext) -> CompanySnapshotResult:
    validate_context(context)
    snapshots = []
    evidence = []
    calculations: list[CalculationProvenance] = []
    limitations = list(context_limitations(context))
    for metric, definition in METRIC_REGISTRY.items():
        observation = latest_observation(
            context.fundamentals.observations, metric, context.as_of_date
        )
        snapshots.append(
            MetricSnapshot(
                metric=metric,
                metric_kind=definition.metric_kind,
                status=ResultStatus.AVAILABLE
                if observation is not None
                else ResultStatus.UNAVAILABLE,
                observation=observation,
                limitations=("NO_CURRENT_OBSERVATION",) if observation is None else (),
            )
        )
        if observation is not None:
            evidence.append(fundamental_evidence(observation))
    windows = []
    for sessions in (5, 20, 60):
        window, references, provenance = summarize_window(context, sessions)
        windows.append(window)
        evidence.extend(references)
        calculations.extend(provenance)
        limitations.extend(window.limitations)
    features, refs, calcs = relative_sma_evidence(context)
    evidence.extend(refs)
    calculations.extend(calcs)
    latest = context.market.observations[-1] if context.market.observations else None
    if latest is not None:
        evidence.append(market_evidence(latest, context.market.metadata))
    return CompanySnapshotResult(
        ticker=context.ticker,
        as_of_date=context.as_of_date,
        quality=context.quality,
        company=context.company,
        latest_market_session=latest.date if latest else None,
        latest_close=latest.close if latest else None,
        market_windows=tuple(windows),
        latest_market_features=features,
        fundamentals=tuple(snapshots),
        evidence=unique_evidence(tuple(evidence)),
        calculation_provenance=tuple(calculations),
        limitations=tuple(dict.fromkeys(limitations)),
    )
