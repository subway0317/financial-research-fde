"""Stable sanitized public errors; never serialize an exception's raw message."""

import logging
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from financial_research.agent.errors import (
    AgentIntegrityError,
    AgentPlanValidationError,
    GroundingValidationError,
    PayloadBudgetExceeded,
)
from financial_research.api.schemas import ErrorResponse
from financial_research.exceptions import (
    ConfigurationError,
    DataValidationError,
    FinancialResearchError,
    InsufficientHistoryError,
    PITViolationError,
    ProviderError,
    UnknownTickerError,
    UnsupportedMetricError,
)
from financial_research.llm.errors import AgentConfigurationError, LLMProviderError
from financial_research.reports.errors import ReportCompilationError, ReportIntegrityError
from financial_research.skills.errors import EvidenceIntegrityError

logger = logging.getLogger(__name__)
ERROR_MAP = (
    (ReportCompilationError, 500, "REPORT_COMPILATION_ERROR", "Report compilation failed."),
    (ReportIntegrityError, 500, "REPORT_INTEGRITY_ERROR", "Report integrity validation failed."),
    (
        PayloadBudgetExceeded,
        503,
        "SYNTHESIS_PAYLOAD_BUDGET_EXCEEDED",
        "Research evidence exceeds the synthesis payload budget.",
    ),
    (AgentConfigurationError, 503, "AGENT_CONFIGURATION_ERROR", "Agent service is not configured."),
    (LLMProviderError, 502, "LLM_PROVIDER_ERROR", "An LLM provider request failed."),
    (AgentPlanValidationError, 500, "AGENT_PLAN_VALIDATION_ERROR", "Agent plan validation failed."),
    (
        GroundingValidationError,
        500,
        "GROUNDING_VALIDATION_ERROR",
        "Answer grounding validation failed.",
    ),
    (AgentIntegrityError, 500, "AGENT_INTEGRITY_ERROR", "Agent integrity validation failed."),
    (
        EvidenceIntegrityError,
        500,
        "EVIDENCE_INTEGRITY_ERROR",
        "Evidence integrity validation failed.",
    ),
    (PITViolationError, 500, "PIT_VIOLATION", "Research integrity validation failed."),
    (UnsupportedMetricError, 422, "UNSUPPORTED_METRIC", "Requested metric is not registered."),
    (
        InsufficientHistoryError,
        422,
        "INSUFFICIENT_HISTORY",
        "Required observed history is unavailable.",
    ),
    (UnknownTickerError, 404, "UNKNOWN_TICKER", "The ticker could not be resolved."),
    (ProviderError, 502, "PROVIDER_ERROR", "An external data provider request failed."),
    (ConfigurationError, 503, "CONFIGURATION_ERROR", "Live research service is not configured."),
    (
        DataValidationError,
        422,
        "DATA_VALIDATION_ERROR",
        "Research data failed canonical validation.",
    ),
)


def request_id(request: Request) -> UUID:
    identifier = getattr(request.state, "request_id", None)
    if not isinstance(identifier, UUID):
        identifier = uuid4()
        request.state.request_id = identifier
    return identifier


def error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    identifier = request_id(request)
    logger.warning(
        "request error request_id=%s endpoint=%s error_code=%s", identifier, request.url.path, code
    )
    body = ErrorResponse(error_code=code, message=message, request_id=identifier)
    return JSONResponse(
        status_code=status,
        content=body.model_dump(mode="json"),
        headers={"X-Request-ID": str(identifier)},
    )


async def domain_error(request: Request, exc: Exception) -> JSONResponse:
    for error_type, status, code, message in ERROR_MAP:
        if isinstance(exc, error_type):
            return error_response(request, status, code, message)
    return error_response(request, 500, "INTERNAL_ERROR", "Internal research service error.")


async def validation_error(request: Request, exc: Exception) -> JSONResponse:
    return error_response(request, 422, "REQUEST_VALIDATION_ERROR", "Invalid research request.")


async def internal_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "internal error request_id=%s exception_type=%s", request_id(request), type(exc).__name__
    )
    return error_response(request, 500, "INTERNAL_ERROR", "Internal research service error.")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(FinancialResearchError, domain_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(Exception, internal_error)
