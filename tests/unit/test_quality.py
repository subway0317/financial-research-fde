from datetime import date

import pytest
from pydantic import ValidationError

from financial_research.quality.checks import evaluate_quality
from financial_research.schemas.quality import QualityIssue, QualityReport, QualityStatus, Severity
from financial_research.schemas.research import ResearchContext


def evaluate(context, *, market=None, fundamentals=None, as_of_date=None):
    return evaluate_quality(
        ticker=context.ticker,
        as_of_date=as_of_date or context.as_of_date,
        company=context.company,
        market=market or context.market,
        fundamentals=fundamentals or context.fundamentals,
    )


def test_all_quality_statuses() -> None:
    assert QualityReport.from_issues(()).status == QualityStatus.PASS
    assert (
        QualityReport.from_issues(
            (QualityIssue(code="STALE", severity=Severity.WARNING, message="stale"),)
        ).status
        == QualityStatus.PASS_WITH_WARNINGS
    )
    assert (
        QualityReport.from_issues(
            (QualityIssue(code="FUTURE", severity=Severity.ERROR, message="future"),)
        ).status
        == QualityStatus.FAIL
    )


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("high", 1, "INVALID_OHLC"),
        ("close", float("nan"), "NONFINITE_NUMERIC"),
        ("open", float("inf"), "NONFINITE_NUMERIC"),
        ("date", date(2025, 5, 26), "FUTURE_MARKET_DATA"),
        ("ticker", "OTHER", "TICKER_MISMATCH"),
    ],
)
def test_invalid_market_has_error_fail(nvda_context, field, value, code) -> None:
    bars = nvda_context.market.observations
    market = nvda_context.market.model_copy(
        update={"observations": (*bars[:-1], bars[-1].model_copy(update={field: value}))}
    )
    report = evaluate(nvda_context, market=market)
    assert report.status == QualityStatus.FAIL
    assert any(i.code == code and i.severity == Severity.ERROR for i in report.issues)


def test_duplicate_market_date_fails(nvda_context) -> None:
    market = nvda_context.market.model_copy(
        update={
            "observations": (
                *nvda_context.market.observations,
                nvda_context.market.observations[-1],
            )
        }
    )
    report = evaluate(nvda_context, market=market)
    assert report.status == QualityStatus.FAIL
    assert any(i.code == "DUPLICATE_MARKET_DATE" for i in report.issues)


def test_missing_required_field_is_explicit(nvda_context) -> None:
    bars = nvda_context.market.observations
    dumped = bars[-1].model_dump()
    del dumped["volume"]
    incomplete = type(bars[-1]).model_construct(**dumped)
    report = evaluate(
        nvda_context,
        market=nvda_context.market.model_copy(update={"observations": (*bars[:-1], incomplete)}),
    )
    assert report.status == QualityStatus.FAIL
    assert any(i.code == "MISSING_REQUIRED_FIELD" for i in report.issues)


@pytest.mark.parametrize(
    "updates,code",
    [
        ({"available_date": date(2025, 5, 27)}, "PIT_VIOLATION"),
        ({"available_date": date(2025, 5, 22)}, "INVALID_AVAILABILITY"),
        ({"period_start": date(2025, 4, 1)}, "INVALID_PERIOD_CHRONOLOGY"),
        ({"period_end": date(2025, 6, 1)}, "INVALID_PERIOD_CHRONOLOGY"),
        ({"metric": "unsupported"}, "UNSUPPORTED_METRIC"),
    ],
)
def test_invalid_fundamentals_fail(nvda_context, updates, code) -> None:
    observations = nvda_context.fundamentals.observations
    fundamentals = nvda_context.fundamentals.model_copy(
        update={"observations": (observations[0].model_copy(update=updates), *observations[1:])}
    )
    report = evaluate(nvda_context, fundamentals=fundamentals)
    assert report.status == QualityStatus.FAIL
    assert any(i.code == code and i.severity == Severity.ERROR for i in report.issues)


@pytest.mark.parametrize("conflicting", [False, True])
def test_canonical_duplicate_severity(nvda_context, conflicting) -> None:
    observations = nvda_context.fundamentals.observations
    duplicate = (
        observations[0].model_copy(update={"value": observations[0].value + 1})
        if conflicting
        else observations[0]
    )
    fundamentals = nvda_context.fundamentals.model_copy(
        update={"observations": (*observations, duplicate)}
    )
    report = evaluate(nvda_context, fundamentals=fundamentals)
    issue = next(i for i in report.issues if i.code == "DUPLICATE_CANONICAL_FUNDAMENTAL")
    assert issue.severity == (Severity.ERROR if conflicting else Severity.WARNING)
    assert report.status == (
        QualityStatus.FAIL if conflicting else QualityStatus.PASS_WITH_WARNINGS
    )


def test_staleness_and_insufficient_history_warn(nvda_context) -> None:
    market = nvda_context.market.model_copy(
        update={
            "observations": nvda_context.market.observations[-10:],
            "features": nvda_context.market.features[-10:],
            "metadata": nvda_context.market.metadata.model_copy(
                update={"requested_end": date(2025, 6, 2)}
            ),
        }
    )
    report = evaluate(nvda_context, market=market, as_of_date=date(2025, 6, 2))
    assert report.status == QualityStatus.PASS_WITH_WARNINGS
    assert {"STALE_MARKET_DATA", "INSUFFICIENT_ROLLING_HISTORY"} <= {i.code for i in report.issues}


def test_context_schema_cannot_claim_pass_with_future_information(nvda_context) -> None:
    observations = nvda_context.fundamentals.observations
    fundamentals = nvda_context.fundamentals.model_copy(
        update={
            "observations": (
                observations[0].model_copy(update={"available_date": date(2025, 5, 27)}),
                *observations[1:],
            )
        }
    )
    with pytest.raises(ValidationError):
        ResearchContext.model_validate(
            {**nvda_context.model_dump(), "fundamentals": fundamentals.model_dump()}
        )
    report = evaluate(nvda_context, fundamentals=fundamentals)
    diagnostic = ResearchContext.model_validate(
        {
            **nvda_context.model_dump(),
            "fundamentals": fundamentals.model_dump(),
            "quality": report.model_dump(),
        }
    )
    assert diagnostic.quality.status == QualityStatus.FAIL
