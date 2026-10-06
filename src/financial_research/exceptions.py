"""Stable errors for callers of the research core."""


class FinancialResearchError(Exception):
    """Base error exposed by the library."""


class UnknownTickerError(FinancialResearchError):
    """The company provider cannot resolve the ticker."""


class ProviderError(FinancialResearchError):
    """An external request failed."""


class DataValidationError(FinancialResearchError):
    """Source data violates the canonical contract."""


class PITViolationError(DataValidationError):
    """Future information has crossed a research boundary."""


class InsufficientHistoryError(DataValidationError):
    """Observed history cannot establish the requested calculation or availability."""


class UnsupportedMetricError(DataValidationError):
    """A requested metric is outside the registered universe."""


class ConfigurationError(FinancialResearchError):
    """Required live provider configuration is absent."""
