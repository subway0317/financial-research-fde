"""Small shared guards and registered request validation."""

from pydantic import ValidationError

from financial_research.exceptions import DataValidationError, PITViolationError
from financial_research.fundamentals.pit import assert_pit_safe
from financial_research.fundamentals.registry import METRIC_REGISTRY, require_metric
from financial_research.schemas.quality import QualityStatus
from financial_research.schemas.research import ResearchContext


def validate_context(context: ResearchContext, *, allow_failed_quality: bool = False) -> None:
    assert_pit_safe(context.fundamentals.observations, context.as_of_date)
    if any(bar.date > context.as_of_date for bar in context.market.observations):
        raise PITViolationError("tool context contains future market observations")
    try:
        ResearchContext.model_validate(context.model_dump())
    except ValidationError as exc:
        raise DataValidationError("tool context failed canonical validation") from exc
    if context.quality.status == QualityStatus.FAIL and not allow_failed_quality:
        raise DataValidationError("research quality FAIL prevents financial calculations")


def metric_names(metrics: list[str] | None) -> tuple[str, ...]:
    if metrics is not None and (
        not isinstance(metrics, list) or any(not isinstance(name, str) for name in metrics)
    ):
        raise DataValidationError("metrics must be a list of canonical metric names")
    names = tuple(METRIC_REGISTRY) if metrics is None else tuple(metrics)
    if not names or len(set(names)) != len(names):
        raise DataValidationError("metrics must be a nonempty unique list")
    for name in names:
        require_metric(name)
    return names


def validate_lookback(lookback_sessions: int) -> None:
    if (
        isinstance(lookback_sessions, bool)
        or not isinstance(lookback_sessions, int)
        or not 2 <= lookback_sessions <= 504
    ):
        raise DataValidationError("lookback_sessions must be an integer from 2 through 504")


def context_limitations(context: ResearchContext) -> tuple[str, ...]:
    return tuple(sorted({issue.code for issue in context.quality.issues}))
