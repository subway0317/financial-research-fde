"""Workflow integrity errors remain typed failures, never partial evidence."""

from pydantic import ValidationError

from financial_research.exceptions import (
    ConfigurationError,
    DataValidationError,
    InsufficientHistoryError,
    PITViolationError,
    ProviderError,
    UnknownTickerError,
    UnsupportedMetricError,
)
from financial_research.schemas.skills import SkillErrorMetadata


class EvidenceIntegrityError(DataValidationError):
    """An evidence ID or calculation provenance has conflicting content."""


class CriticalQualityError(DataValidationError):
    """Authoritative Stage 1 quality FAIL blocks research execution."""


def safe_error(exc: Exception, target: str) -> SkillErrorMetadata:
    mapping = (
        (
            EvidenceIntegrityError,
            "EVIDENCE_INTEGRITY_ERROR",
            "Evidence integrity validation failed.",
        ),
        (CriticalQualityError, "CRITICAL_QUALITY_FAILURE", "Research quality prevents execution."),
        (PITViolationError, "PIT_VIOLATION", "Point-in-time integrity validation failed."),
        (UnsupportedMetricError, "UNSUPPORTED_METRIC", "Requested metric is not registered."),
        (InsufficientHistoryError, "INSUFFICIENT_HISTORY", "Required history is unavailable."),
        (UnknownTickerError, "UNKNOWN_TICKER", "The ticker could not be resolved."),
        (ProviderError, "PROVIDER_ERROR", "An external data provider request failed."),
        (ConfigurationError, "CONFIGURATION_ERROR", "Live research is not configured."),
        (DataValidationError, "DATA_VALIDATION_ERROR", "Canonical data validation failed."),
        (ValidationError, "DATA_VALIDATION_ERROR", "Typed contract validation failed."),
    )
    for error_type, code, message in mapping:
        if isinstance(exc, error_type):
            return SkillErrorMetadata(error_code=code, message=message, target=target)
    return SkillErrorMetadata(
        error_code="INTERNAL_ERROR", message="Internal skill execution failed.", target=target
    )
