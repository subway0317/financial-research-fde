"""Request-local safe diagnostics survive sanitized Skill/Agent error conversion."""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

import httpx

ProviderOperation = Literal[
    "request",
    "fetch_company_tickers",
    "fetch_companyfacts",
    "fetch_submissions",
    "fetch_submissions_archive",
    "fetch_market_history",
]


@dataclass(frozen=True)
class ProviderFailure:
    provider: str
    operation: ProviderOperation
    exception_type: str
    upstream_status: int | None = None


@dataclass
class ProviderFailureState:
    # A shared container carries worker-thread observations back to the ASGI task.
    # Only safe scalars are retained, never exception/request/response objects.
    failure: ProviderFailure | None = None


provider_failure_state: ContextVar[ProviderFailureState | None] = ContextVar(
    "provider_failure_state", default=None
)


def capture_provider_failure(provider: str, operation: ProviderOperation, exc: Exception) -> None:
    state = provider_failure_state.get()
    if state is None:
        return
    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
    state.failure = ProviderFailure(
        provider=provider if provider in {"sec-edgar", "yahoo-chart"} else "unknown",
        operation=operation,
        exception_type=type(exc).__name__,
        upstream_status=status if type(status) is int and 100 <= status <= 599 else None,
    )
