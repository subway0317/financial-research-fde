"""Envelope metadata and request logging; no financial computations."""

import logging
import time
from datetime import UTC, datetime

from fastapi import Request

from financial_research.api.errors import request_id
from financial_research.api.schemas import ResearchEnvelope
from financial_research.public_research.projection import project_tool_result
from financial_research.public_research.schemas import PublicToolResult
from financial_research.schemas.tools import ToolResult

logger = logging.getLogger(__name__)


def envelope(
    request: Request, result: ToolResult, tool_name: str
) -> ResearchEnvelope[PublicToolResult]:
    identifier = request_id(request)
    duration = (time.perf_counter() - request.state.started_at) * 1000
    logger.info(
        "research request request_id=%s endpoint=%s ticker=%s as_of_date=%s "
        "tool_name=%s duration_ms=%.3f quality=%s",
        identifier,
        request.url.path,
        result.ticker,
        result.as_of_date,
        tool_name,
        duration,
        result.quality.status,
    )
    return ResearchEnvelope(
        request_id=identifier,
        generated_at=datetime.now(UTC),
        data=project_tool_result(result),
        quality=result.quality,
        limitations=result.limitations,
    )
