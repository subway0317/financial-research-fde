"""One comparable-period engine shared by all fundamental research tools.

Latest period end first, then annual before quarterly at the same endpoint.
Within one exact period, latest legally available filing wins; conflicting ties
are invalid. Prior-year pairs require exact fiscal frequency/quarter/year labels
and compatible period durations. No sequential, date-only, or YTD fallback.
"""

from dataclasses import dataclass
from datetime import date

from financial_research.exceptions import DataValidationError
from financial_research.fundamentals.pit import assert_pit_safe
from financial_research.fundamentals.registry import PeriodType, require_metric
from financial_research.schemas.fundamentals import FundamentalObservation
from financial_research.schemas.periods import PeriodFrequency


@dataclass(frozen=True)
class ComparablePair:
    current: FundamentalObservation | None
    prior: FundamentalObservation | None
    reason: str | None = None


def latest_observation(
    observations: tuple[FundamentalObservation, ...], metric: str, as_of_date: date
) -> FundamentalObservation | None:
    definition = require_metric(metric)
    assert_pit_safe(observations, as_of_date)
    candidates = [o for o in observations if o.metric == metric]
    if not candidates:
        return None
    if any(
        o.unit != definition.unit
        or ((definition.period_type == PeriodType.DURATION) != (o.period_start is not None))
        for o in candidates
    ):
        raise DataValidationError("canonical metric unit/duration contract mismatch")
    latest_end = max(o.period_end for o in candidates)
    candidates = [o for o in candidates if o.period_end == latest_end]
    labeled = [o for o in candidates if o.fiscal_period is not None]
    if labeled:
        annual = [
            o
            for o in labeled
            if o.fiscal_period is not None and o.fiscal_period.frequency == PeriodFrequency.ANNUAL
        ]
        candidates = annual or labeled
    # Do not choose randomly between different durations sharing one endpoint.
    periods = {(o.period_start, o.period_end) for o in candidates}
    if len(periods) != 1:
        return None
    return _latest_vintage(candidates)


def select_comparable_pair(
    observations: tuple[FundamentalObservation, ...], metric: str, as_of_date: date
) -> ComparablePair:
    current = latest_observation(observations, metric, as_of_date)
    if current is None:
        return ComparablePair(
            None,
            None,
            "AMBIGUOUS_CURRENT_PERIOD"
            if any(o.metric == metric for o in observations)
            else "NO_CURRENT_OBSERVATION",
        )
    period = current.fiscal_period
    if period is None:
        return ComparablePair(current, None, "UNVERIFIED_FISCAL_PERIOD")
    candidates = []
    for observation in observations:
        prior_period = observation.fiscal_period
        if observation.metric != metric or prior_period is None:
            continue
        if (
            prior_period.frequency == period.frequency
            and prior_period.fiscal_year == period.fiscal_year - 1
            and prior_period.fiscal_quarter == period.fiscal_quarter
            and observation.period_end < current.period_end
            and observation.unit == current.unit
        ):
            candidates.append(observation)
    if not candidates:
        return ComparablePair(current, None, "NO_COMPARABLE_PRIOR_PERIOD")
    if len({(o.period_start, o.period_end) for o in candidates}) != 1:
        return ComparablePair(current, None, "AMBIGUOUS_PRIOR_PERIOD")
    prior = _latest_vintage(candidates)
    if not 330 <= (current.period_end - prior.period_end).days <= 400:
        return ComparablePair(current, None, "INCOMPATIBLE_FISCAL_YEAR_SPACING")
    if current.period_start is not None and prior.period_start is not None:
        # A 52/53-week fiscal calendar may differ by one week, not by a YTD span.
        if (
            abs(
                (current.period_end - current.period_start).days
                - (prior.period_end - prior.period_start).days
            )
            > 14
        ):
            return ComparablePair(current, None, "INCOMPATIBLE_PERIOD_DURATION")
    return ComparablePair(current, prior)


def _latest_vintage(candidates: list[FundamentalObservation]) -> FundamentalObservation:
    latest_date = max((o.available_date, o.filed_at) for o in candidates)
    latest = [o for o in candidates if (o.available_date, o.filed_at) == latest_date]
    if (
        len({o.value for o in latest}) != 1
        or len(
            {
                (
                    o.fiscal_period.frequency,
                    o.fiscal_period.fiscal_year,
                    o.fiscal_period.fiscal_quarter,
                )
                if o.fiscal_period
                else None
                for o in latest
            }
        )
        != 1
    ):
        raise DataValidationError("conflicting latest filing vintages")
    return min(latest, key=lambda o: (o.accession_number, o.source_reference))
