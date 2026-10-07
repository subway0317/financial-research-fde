"""Stateless application factory; default import performs no provider requests."""

import logging
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response

from financial_research.api.dependencies import AgentFactory, ToolsFactory
from financial_research.api.errors import install_error_handlers
from financial_research.api.routes.agent import router as agent_router
from financial_research.api.routes.health import router as health_router
from financial_research.api.routes.reports import router as reports_router
from financial_research.api.routes.research import router as research_router
from financial_research.config import ResearchConfig
from financial_research.research.live import LiveContextBuilder
from financial_research.tools.service import ResearchTools

logger = logging.getLogger(__name__)


def create_app(
    *,
    tools_factory: ToolsFactory | None = None,
    config: ResearchConfig | None = None,
    agent_factory: AgentFactory | None = None,
    include_metadata: bool = True,
) -> FastAPI:
    application = FastAPI(title="Financial Research FDE", version="0.4.0")
    application.state.agent_factory = agent_factory
    application.state.research_config = config
    application.state.tools_factory = tools_factory or (
        lambda: ResearchTools(LiveContextBuilder(config))
    )
    install_error_handlers(application)

    async def metadata(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = uuid4()
        request.state.started_at = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request.state.request_id)
        logger.info(
            "HTTP request request_id=%s endpoint=%s status=%d duration_ms=%.3f",
            request.state.request_id,
            request.url.path,
            response.status_code,
            (time.perf_counter() - request.state.started_at) * 1000,
        )
        return response

    if include_metadata:
        application.middleware("http")(metadata)

    application.include_router(health_router)
    application.include_router(research_router)
    application.include_router(agent_router)
    application.include_router(reports_router)
    return application


app = create_app()
