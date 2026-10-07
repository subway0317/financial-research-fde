"""Sanitized report failures; exception text never contains artifact or provider inputs."""

from financial_research.exceptions import FinancialResearchError


class ReportCompilationError(FinancialResearchError):
    """The compiler did not receive a compatible validated Agent answer."""


class ReportIntegrityError(FinancialResearchError):
    """Report or cross-file integrity failed."""


class ReportBundleWriteError(FinancialResearchError):
    """A bundle could not be safely finalized; existing bundles are never overwritten."""
