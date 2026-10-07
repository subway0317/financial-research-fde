"""Thin production composition over the existing API, with no research changes."""

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.staticfiles import StaticFiles

from financial_research.api.app import create_app
from financial_research.api.dependencies import AgentFactory, ToolsFactory
from financial_research.api.errors import error_response
from financial_research.config import ResearchConfig
from financial_research.deployment.assets import frontend_available
from financial_research.deployment.config import DeploymentConfig
from financial_research.deployment.guard import DemoBusyError, ResearchGuard, install_guards
from financial_research.deployment.middleware import BUSY_MESSAGE, OperationalMiddleware


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ready", "not_ready"]
    environment: Literal["development", "test", "production"]
    codes: list[str]


class VersionResponse(BaseModel):
    app: Literal["financial-research-fde"] = "financial-research-fde"
    version: str
    commit: str
    environment: Literal["development", "test", "production"]


def create_production_app(
    *,
    deployment_config: DeploymentConfig | None = None,
    frontend_dir: Path | None = None,
    agent_factory: AgentFactory | None = None,
    tools_factory: ToolsFactory | None = None,
) -> FastAPI:
    settings = deployment_config or DeploymentConfig.from_env()
    directory = frontend_dir or Path("frontend/dist")
    application = create_app(
        agent_factory=agent_factory,
        tools_factory=tools_factory,
        config=ResearchConfig.from_env().model_copy(
            update={
                "market_data_provider": settings.market_data_provider,
                "tiingo_api_token": settings.tiingo_api_token,
            }
        ),
        include_metadata=False,
    )
    application.state.deployment_config = settings
    application.state.initialized = True
    guard = ResearchGuard()
    application.state.research_guard = guard
    if settings.environment == "production":
        install_guards(application, guard)

    async def busy(request: Request, exc: Exception) -> JSONResponse:
        return error_response(request, 429, "DEMO_BUSY", BUSY_MESSAGE)

    application.add_exception_handler(DemoBusyError, busy)

    @application.get(
        "/ready", response_model=ReadinessResponse, responses={503: {"model": ReadinessResponse}}
    )
    def ready() -> JSONResponse:
        codes = settings.readiness_codes()
        if not application.state.initialized:
            codes.append("APP_NOT_INITIALIZED")
        if not frontend_available(directory):
            codes.append("FRONTEND_UNAVAILABLE")
        result = ReadinessResponse(
            status="not_ready" if codes else "ready", environment=settings.environment, codes=codes
        )
        return JSONResponse(status_code=503 if codes else 200, content=result.model_dump())

    @application.get("/version", response_model=VersionResponse)
    def version() -> VersionResponse:
        return VersionResponse(
            version=application.version, commit=settings.commit, environment=settings.environment
        )

    @application.get("/", include_in_schema=False, response_model=None)
    def index(request: Request) -> FileResponse | JSONResponse:
        if not frontend_available(directory):
            return error_response(request, 503, "FRONTEND_UNAVAILABLE", "Frontend is unavailable.")
        return FileResponse(directory / "index.html", headers={"Cache-Control": "no-cache"})

    application.mount(
        "/assets", StaticFiles(directory=directory / "assets", check_dir=False), name="assets"
    )
    # OpenAPI expands included routers on both older and lazy-router FastAPI versions.
    paths = application.openapi()["paths"]
    application.add_middleware(
        OperationalMiddleware,
        config=settings,
        guard=guard,
        protected_paths={
            path
            for path, operations in paths.items()
            if path.startswith("/v1/") and "post" in operations
        },
        known_paths=set(paths) | {"/", "/docs", "/openapi.json", "/redoc"},
    )
    return application


app = create_production_app()
