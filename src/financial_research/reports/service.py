"""Single fixed report workflow through the shared Agent execution path."""

from datetime import UTC, datetime
from uuid import uuid4

from financial_research.agent.service import ResearchAgent
from financial_research.reports.compiler import ReportCompiler
from financial_research.reports.errors import ReportCompilationError
from financial_research.reports.manifest import build_manifest, evidence_artifact
from financial_research.reports.rendering import render_markdown
from financial_research.reports.schemas import (
    EquityResearchReportRequest,
    EquityResearchReportResponse,
)
from financial_research.reports.validation import ReportBundleValidator
from financial_research.schemas.agent import (
    AgentIntent,
    AgentPlan,
    AgentReasonCode,
    ResearchAgentRequest,
)

REPORT_TASK_V1 = (
    "Prepare a broad evidence-grounded equity research report covering company context, "
    "fundamentals, market behavior, data quality, and limitations as of the requested date."
)


class ReportWorkflowService:
    def __init__(self, agent: ResearchAgent) -> None:
        self._agent = agent

    def run(self, request: EquityResearchReportRequest) -> EquityResearchReportResponse:
        request = EquityResearchReportRequest.model_validate(request.model_dump())
        run_id, created_at = uuid4(), datetime.now(UTC)
        agent_request = ResearchAgentRequest(
            question=REPORT_TASK_V1,
            ticker=request.ticker,
            as_of_date=request.as_of_date,
            response_language=request.response_language,
        )
        plan = AgentPlan(
            plan_version="1.0",
            intent=AgentIntent.BROAD_RESEARCH,
            selected_skill_id="equity_research",
            reason_code=AgentReasonCode.BROAD_EQUITY_RESEARCH_REQUEST,
            ticker=request.ticker,
            as_of_date=request.as_of_date,
            requested_focus=None,
        )
        answer = self._agent.execute_validated_plan(agent_request, plan)
        if (answer.ticker, answer.as_of_date, answer.response_language) != (
            request.ticker,
            request.as_of_date,
            request.response_language,
        ):
            raise ReportCompilationError("REPORT_REQUEST_IDENTITY_CHANGED")
        report = ReportCompiler().compile(
            answer,
            run_id=run_id,
            created_at=created_at,
            provider=self._agent.llm_provider,
            model=self._agent.llm_model,
        )
        markdown, manifest = render_markdown(report), build_manifest(report)
        ReportBundleValidator().validate(report, markdown, evidence_artifact(report), manifest)
        return EquityResearchReportResponse(
            report=report, markdown=markdown, manifest_summary=manifest
        )
