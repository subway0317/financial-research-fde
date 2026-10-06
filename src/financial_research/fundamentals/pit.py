"""Pure daily PIT engine; calendar coverage is explicit and never inferred.

Filing calendar date is excluded irrespective of submission time. Availability is
strictly the next observed trading session. No downloads or wall clock are used.
"""

from bisect import bisect_right
from datetime import date

from pydantic import model_validator

from financial_research.exceptions import InsufficientHistoryError, PITViolationError
from financial_research.schemas.base import CanonicalModel
from financial_research.schemas.fundamentals import FundamentalObservation


class ObservedSessionCalendar(CanonicalModel):
    coverage_start: date
    coverage_end: date
    sessions: tuple[date, ...]

    @model_validator(mode="after")
    def valid_calendar(self) -> "ObservedSessionCalendar":
        if self.coverage_start > self.coverage_end:
            raise ValueError("invalid calendar coverage")
        if list(self.sessions) != sorted(set(self.sessions)):
            raise ValueError("sessions must be strictly increasing and unique")
        if any(not self.coverage_start <= d <= self.coverage_end for d in self.sessions):
            raise ValueError("session outside calendar coverage")
        return self


def next_observed_session(filed_at: date, calendar: ObservedSessionCalendar) -> date | None:
    if filed_at < calendar.coverage_start:
        raise InsufficientHistoryError("filing predates observed calendar coverage")
    position = bisect_right(calendar.sessions, filed_at)
    return calendar.sessions[position] if position < len(calendar.sessions) else None


def select_available(
    observations: tuple[FundamentalObservation, ...], as_of_date: date
) -> tuple[FundamentalObservation, ...]:
    """Legal source-history filtering; future observations are expected at this input."""
    return tuple(
        sorted(
            (o for o in observations if o.available_date <= as_of_date),
            key=lambda o: (
                o.metric,
                o.period_end,
                o.period_start or date.min,
                o.available_date,
                o.accession_number,
            ),
        )
    )


def assert_pit_safe(observations: tuple[FundamentalObservation, ...], as_of_date: date) -> None:
    """Enforce the invariant at an already selected service/context boundary."""
    if any(observation.available_date > as_of_date for observation in observations):
        raise PITViolationError("fundamental availability exceeds as_of_date")
