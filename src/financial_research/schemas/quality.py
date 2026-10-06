"""Typed diagnostic and aggregate quality results."""

from datetime import date
from enum import StrEnum

from pydantic import model_validator

from financial_research.schemas.base import CanonicalModel, NonEmpty


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class QualityStatus(StrEnum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    FAIL = "FAIL"


class QualityIssue(CanonicalModel):
    code: NonEmpty
    severity: Severity
    message: NonEmpty
    affected_field: str | None = None
    affected_date: date | None = None
    affected_context: str | None = None


class QualityReport(CanonicalModel):
    status: QualityStatus
    issues: tuple[QualityIssue, ...] = ()

    @model_validator(mode="after")
    def consistent_status(self) -> "QualityReport":
        expected = self.status_for(self.issues)
        if self.status != expected:
            raise ValueError(f"quality status must be {expected}")
        return self

    @staticmethod
    def status_for(issues: tuple[QualityIssue, ...]) -> QualityStatus:
        if any(i.severity == Severity.ERROR for i in issues):
            return QualityStatus.FAIL
        if any(i.severity == Severity.WARNING for i in issues):
            return QualityStatus.PASS_WITH_WARNINGS
        return QualityStatus.PASS

    @classmethod
    def from_issues(cls, issues: tuple[QualityIssue, ...]) -> "QualityReport":
        return cls(status=cls.status_for(issues), issues=issues)
