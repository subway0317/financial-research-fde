"""Pure ASGI operations: early access refusal, safe request IDs, and completion logging."""

import hmac
import logging
import time
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from financial_research.api.errors import error_response
from financial_research.deployment.config import DeploymentConfig
from financial_research.deployment.guard import ResearchGuard

logger = logging.getLogger(__name__)
BUSY_MESSAGE = "Another research report is currently being generated. Please try again shortly."
EXPENSIVE_PATHS = {"/v1/reports/equity-research", "/v1/agent/research"}


class OperationalMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        config: DeploymentConfig,
        guard: ResearchGuard,
        protected_paths: set[str],
        known_paths: set[str],
    ) -> None:
        self.app, self.config, self.guard = app, config, guard
        self.protected_paths, self.known_paths = protected_paths, known_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        identifier = uuid4()
        scope.setdefault("state", {})["request_id"] = identifier
        scope["state"]["started_at"] = started
        request = Request(scope, receive)
        status, response_started = 500, False

        async def send_metadata(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status, response_started = message["status"], True
                MutableHeaders(scope=message)["X-Request-ID"] = str(identifier)
            await send(message)

        try:
            if self.config.environment == "production" and scope["method"] == "POST":
                if scope["path"] in self.protected_paths:
                    token = self.config.demo_access_token
                    if token is None:
                        await error_response(
                            request,
                            503,
                            "DEMO_ACCESS_UNAVAILABLE",
                            "Demo access is not configured.",
                        )(scope, receive, send_metadata)
                        return
                    supplied = Headers(scope=scope).get("X-Demo-Access", "").encode("latin-1")
                    if not hmac.compare_digest(supplied, token.get_secret_value().encode("utf-8")):
                        await error_response(
                            request,
                            401,
                            "DEMO_ACCESS_REQUIRED",
                            "A valid demo access code is required.",
                        )(scope, receive, send_metadata)
                        return
                if scope["path"] in EXPENSIVE_PATHS and self.guard.busy:
                    await error_response(request, 429, "DEMO_BUSY", BUSY_MESSAGE)(
                        scope, receive, send_metadata
                    )
                    return
            await self.app(scope, receive, send_metadata)
        except Exception:
            if response_started:
                status = 500
                raise
            await error_response(
                request, 500, "INTERNAL_ERROR", "Internal research service error."
            )(scope, receive, send_metadata)
        finally:
            path = scope["path"]
            safe_path = (
                path
                if path in self.known_paths
                else ("/assets/*" if path.startswith("/assets/") else "unmatched")
            )
            logger.info(
                "HTTP request completed",
                extra={
                    "event": "http_request",
                    "request_id": str(identifier),
                    "method": scope["method"]
                    if scope["method"]
                    in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
                    else "OTHER",
                    "path": safe_path,
                    "status_code": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                },
            )
