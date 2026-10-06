from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from financial_research.exceptions import InsufficientHistoryError, PITViolationError
from financial_research.fundamentals.pit import (
    ObservedSessionCalendar,
    assert_pit_safe,
    next_observed_session,
    select_available,
)
from financial_research.schemas.fundamentals import FundamentalObservation


def observation() -> FundamentalObservation:
    # Logical boundary fixture, not evidence of an actual NVDA filing.
    return FundamentalObservation(
        ticker="ABC",
        metric="revenue",
        value="100",
        unit="USD",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 3, 31),
        filed_at=date(2025, 5, 22),
        available_date=date(2025, 5, 23),
        form="10-Q",
        accession_number="synthetic-001",
        provider="fixture",
        source_reference="fixture://logical-pit",
        retrieved_at=datetime(2025, 6, 1, tzinfo=UTC),
        data_vintage="logical-v1",
    )


def test_exact_pit_boundary() -> None:
    data = (observation(),)
    assert select_available(data, date(2025, 5, 22)) == ()
    assert select_available(data, date(2025, 5, 23)) == data
    with pytest.raises(PITViolationError):
        assert_pit_safe(data, date(2025, 5, 22))
    assert_pit_safe(data, date(2025, 5, 23))


def test_next_observed_session_skips_weekend_and_holiday() -> None:
    calendar = ObservedSessionCalendar(
        coverage_start=date(2025, 5, 22),
        coverage_end=date(2025, 5, 27),
        sessions=(date(2025, 5, 22), date(2025, 5, 23), date(2025, 5, 27)),
    )
    assert next_observed_session(date(2025, 5, 22), calendar) == date(2025, 5, 23)
    assert next_observed_session(date(2025, 5, 23), calendar) == date(2025, 5, 27)
    assert next_observed_session(date(2025, 5, 24), calendar) == date(2025, 5, 27)
    assert next_observed_session(date(2025, 5, 27), calendar) is None
    with pytest.raises(InsufficientHistoryError):
        next_observed_session(date(2025, 5, 21), calendar)


@pytest.mark.parametrize(
    "update",
    [
        {"period_start": date(2025, 4, 1)},
        {"filed_at": date(2025, 3, 30)},
        {"available_date": date(2025, 5, 22)},
        {"value": "NaN"},
        {"value": "Infinity"},
    ],
)
def test_invalid_financial_chronology_or_numeric(update: dict) -> None:
    with pytest.raises(ValidationError):
        FundamentalObservation.model_validate({**observation().model_dump(), **update})


def test_calendar_rejects_unsorted_duplicate_sessions() -> None:
    with pytest.raises(ValidationError):
        ObservedSessionCalendar(
            coverage_start=date(2025, 5, 22),
            coverage_end=date(2025, 5, 27),
            sessions=(date(2025, 5, 23), date(2025, 5, 23)),
        )
