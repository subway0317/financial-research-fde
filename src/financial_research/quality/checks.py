"""Small deterministic quality checks over canonical data; no source repair."""

from collections import Counter
from datetime import date

from pydantic import ValidationError

from financial_research.fundamentals.pit import ObservedSessionCalendar, next_observed_session
from financial_research.fundamentals.registry import METRIC_REGISTRY, PeriodType
from financial_research.schemas.base import CanonicalModel
from financial_research.schemas.company import CompanyProfile
from financial_research.schemas.fundamentals import FundamentalResearch
from financial_research.schemas.market import MarketResearch
from financial_research.schemas.quality import QualityIssue, QualityReport, Severity


def _validation_issues(model: CanonicalModel, context: str) -> tuple[QualityIssue, ...]:
    try:
        type(model).model_validate(model.model_dump())
    except ValidationError as exc:
        issues = []
        for error in exc.errors(include_url=False, include_input=False):
            kind = error["type"]
            message = error["msg"]
            code = "INVALID_REQUIRED_FIELD"
            if kind == "missing":
                code = "MISSING_REQUIRED_FIELD"
            elif kind in {"finite_number", "decimal_max_digits"}:
                code = "NONFINITE_NUMERIC"
            elif "OHLC" in message or "low exceeds high" in message:
                code = "INVALID_OHLC"
            elif "period_" in message:
                code = "INVALID_PERIOD_CHRONOLOGY"
            elif "availability" in message:
                code = "INVALID_AVAILABILITY"
            issues.append(
                QualityIssue(
                    code=code,
                    severity=Severity.ERROR,
                    message=message,
                    affected_field=".".join(str(part) for part in error["loc"]) or None,
                    affected_context=context,
                )
            )
        return tuple(issues)
    return ()


def evaluate_quality(
    *,
    ticker: str,
    as_of_date: date,
    company: CompanyProfile,
    market: MarketResearch,
    fundamentals: FundamentalResearch,
    stale_market_days: int = 7,
) -> QualityReport:
    issues = list(fundamentals.issues)
    issues.extend(_validation_issues(company, "company"))
    issues.extend(_validation_issues(market.metadata, "market.metadata"))
    if company.ticker != ticker:
        issues.append(_error("TICKER_MISMATCH", "company ticker differs from requested ticker"))
    # The SEC directory is current reference identity, not an archived security master.
    issues.append(
        QualityIssue(
            code="CURRENT_COMPANY_REFERENCE",
            severity=Severity.WARNING,
            message="company reference snapshot; historical identity unverified",
            affected_field="company",
        )
    )
    issues.append(
        QualityIssue(
            code="RETRIEVED_MARKET_VINTAGE",
            severity=Severity.WARNING,
            message="prices use retrieved adjustment vintage; archived as-of vintage unverified",
            affected_field="market.metadata.provenance.data_vintage",
        )
    )
    if company.currency is None:
        issues.append(
            QualityIssue(
                code="MISSING_COMPANY_CURRENCY",
                severity=Severity.WARNING,
                message="company reference source does not establish reporting currency",
                affected_field="company.currency",
            )
        )
    elif company.currency != market.metadata.currency:
        issues.append(_error("CURRENCY_MISMATCH", "company and market currencies differ"))
    if market.metadata.requested_end != as_of_date:
        issues.append(
            _error("REQUEST_COVERAGE_MISMATCH", "market coverage differs from as_of_date")
        )
    dates = [bar.date for bar in market.observations]
    for session, count in sorted(Counter(dates).items()):
        if count > 1:
            issues.append(_error("DUPLICATE_MARKET_DATE", "duplicate observed session", session))
    if dates != sorted(dates):
        issues.append(_error("UNSORTED_MARKET_DATES", "market sessions are not chronological"))
    for bar in market.observations:
        issues.extend(_validation_issues(bar, f"market:{bar.date}"))
        if bar.ticker != ticker:
            issues.append(_error("TICKER_MISMATCH", "market ticker differs", bar.date))
        if bar.date > as_of_date:
            issues.append(_error("FUTURE_MARKET_DATA", "market date exceeds as_of_date", bar.date))
        if bar.date < market.metadata.requested_start:
            issues.append(_error("OUT_OF_SCOPE_MARKET_DATA", "bar predates request", bar.date))
    if not dates:
        issues.append(_error("MISSING_MARKET_DATA", "no observed market sessions"))
    else:
        if (as_of_date - max(dates)).days > stale_market_days:
            issues.append(
                QualityIssue(
                    code="STALE_MARKET_DATA",
                    severity=Severity.WARNING,
                    message=f"latest session exceeds {stale_market_days}-day freshness threshold",
                    affected_date=max(dates),
                )
            )
        if len(dates) < 61:
            issues.append(
                QualityIssue(
                    code="INSUFFICIENT_ROLLING_HISTORY",
                    severity=Severity.WARNING,
                    message="60-return volatility requires 61 closes; warm-up is null",
                    affected_field="market.features",
                )
            )
    if [feature.date for feature in market.features] != dates:
        issues.append(_error("FEATURE_ALIGNMENT", "feature dates differ from observed sessions"))
    for feature in market.features:
        issues.extend(_validation_issues(feature, f"features:{feature.date}"))
    keys: dict[tuple[object, ...], list[object]] = {}
    calendar = None
    if (
        dates == sorted(set(dates))
        and all(market.metadata.requested_start <= d <= as_of_date for d in dates)
        and market.metadata.requested_start <= as_of_date
    ):
        calendar = ObservedSessionCalendar(
            coverage_start=market.metadata.requested_start,
            coverage_end=as_of_date,
            sessions=tuple(dates),
        )
    for observation in fundamentals.observations:
        issues.extend(
            _validation_issues(observation, f"fundamental:{observation.accession_number}")
        )
        if observation.ticker != ticker:
            issues.append(_error("TICKER_MISMATCH", "fundamental ticker differs"))
        definition = METRIC_REGISTRY.get(observation.metric)
        if definition is None:
            issues.append(
                _error("UNSUPPORTED_METRIC", f"unregistered metric: {observation.metric}")
            )
        else:
            if observation.unit != definition.unit:
                issues.append(_error("UNSUPPORTED_UNIT", f"unexpected unit: {observation.unit}"))
            if (definition.period_type == PeriodType.DURATION) != (
                observation.period_start is not None
            ):
                issues.append(_error("INVALID_PERIOD_TYPE", "duration/instant contract mismatch"))
        if observation.available_date > as_of_date:
            issues.append(
                _error(
                    "PIT_VIOLATION",
                    "fundamental availability exceeds as_of_date",
                    observation.available_date,
                )
            )
        if calendar is not None:
            if observation.filed_at < calendar.coverage_start:
                issues.append(_error("AVAILABILITY_COVERAGE", "filing predates observed calendar"))
            elif (
                next_observed_session(observation.filed_at, calendar) != observation.available_date
            ):
                issues.append(
                    _error(
                        "INVALID_AVAILABILITY_SESSION",
                        "availability differs from strictly next observed session",
                    )
                )
        key = (
            observation.ticker,
            observation.metric,
            observation.unit,
            observation.period_start,
            observation.period_end,
            observation.filed_at,
            observation.accession_number,
        )
        keys.setdefault(key, []).append(observation.value)
    for duplicate_key, values in keys.items():
        if len(values) > 1:
            conflicting = len(set(values)) > 1
            issues.append(
                QualityIssue(
                    code="DUPLICATE_CANONICAL_FUNDAMENTAL",
                    severity=Severity.ERROR if conflicting else Severity.WARNING,
                    message="conflicting duplicates"
                    if conflicting
                    else "identical canonical duplicates",
                    affected_field=str(duplicate_key[1]),
                    affected_context=str(duplicate_key[-1]),
                )
            )
    if not fundamentals.observations:
        issues.append(
            QualityIssue(
                code="MISSING_FUNDAMENTALS",
                severity=Severity.WARNING,
                message="no legally available fundamental observations",
            )
        )
    return QualityReport.from_issues(tuple(issues))


def _error(code: str, message: str, session: date | None = None) -> QualityIssue:
    return QualityIssue(code=code, severity=Severity.ERROR, message=message, affected_date=session)
