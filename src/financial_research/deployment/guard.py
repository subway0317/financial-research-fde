"""A single synchronous research slot, held until the underlying worker actually exits."""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import Lock

from fastapi import FastAPI, Request

from financial_research.agent.service import ResearchAgent
from financial_research.api.dependencies import (
    get_report_workflow,
    get_research_agent,
)
from financial_research.api.schemas import AgentResearchRequest
from financial_research.exceptions import FinancialResearchError
from financial_research.reports.schemas import (
    EquityResearchReportRequest,
    EquityResearchReportResponse,
)
from financial_research.reports.service import ReportWorkflowService
from financial_research.schemas.agent import GroundedResearchAnswer, ResearchAgentRequest

logger = logging.getLogger(__name__)


class DemoBusyError(FinancialResearchError):
    """Operational refusal, separate from research readiness or quality."""


class ResearchGuard:
    def __init__(self) -> None:
        self._lock = Lock()

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    def run[T](self, operation: Callable[[], T]) -> T:
        if not self._lock.acquire(blocking=False):
            raise DemoBusyError("Research generation is busy.")
        try:
            return operation()
        finally:
            self._lock.release()


class GuardedReportWorkflow:
    def __init__(self, service: ReportWorkflowService, guard: ResearchGuard, request: Request):
        self._service, self._guard, self._request = service, guard, request

    def run(self, body: EquityResearchReportRequest) -> EquityResearchReportResponse:
        result = self._guard.run(lambda: self._service.run(body))
        logger.info(
            "report completed",
            extra={
                "event": "report_completed",
                "request_id": str(self._request.state.request_id),
                "ticker": result.report.ticker,
                "as_of_date": str(result.report.as_of_date),
                "report_status": result.report.status.value,
                "report_id": result.report.report_id,
                "run_id": str(result.report.run_id),
                "repair_count": result.report.runtime_metadata.repair_count,
            },
        )
        return result


class GuardedAgent:
    def __init__(self, agent: ResearchAgent, guard: ResearchGuard):
        self._agent, self._guard = agent, guard

    def run(self, body: ResearchAgentRequest) -> GroundedResearchAnswer:
        return self._guard.run(lambda: self._agent.run(body))


def install_guards(application: FastAPI, guard: ResearchGuard) -> None:
    def report(
        request: Request, body: EquityResearchReportRequest
    ) -> Iterator[GuardedReportWorkflow]:
        with contextmanager(get_report_workflow)(request, body) as service:
            yield GuardedReportWorkflow(service, guard, request)

    def agent(request: Request, body: AgentResearchRequest) -> Iterator[GuardedAgent]:
        with contextmanager(get_research_agent)(request, body) as service:
            yield GuardedAgent(service, guard)

    application.dependency_overrides[get_report_workflow] = report
    application.dependency_overrides[get_research_agent] = agent
