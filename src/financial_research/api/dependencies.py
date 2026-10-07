"""Replaceable factories; live providers are created lazily inside each build."""

from collections.abc import Callable, Iterator
from typing import cast

from fastapi import Request

from financial_research.agent.service import ResearchAgent
from financial_research.api.runtime import live_agent
from financial_research.api.schemas import AgentResearchRequest
from financial_research.llm.openai_responses import OpenAIResponsesClient
from financial_research.reports.schemas import EquityResearchReportRequest
from financial_research.reports.service import ReportWorkflowService
from financial_research.research.live import LiveContextBuilder
from financial_research.skills.defaults import create_skill_registry
from financial_research.tools.service import ResearchTools

ToolsFactory = Callable[[], ResearchTools]
AgentFactory = Callable[[], ResearchAgent]


def get_research_tools(request: Request) -> ResearchTools:
    factory = cast(ToolsFactory, request.app.state.tools_factory)
    return factory()


def get_research_agent(request: Request, body: AgentResearchRequest) -> Iterator[ResearchAgent]:
    # FastAPI validates the shared body before constructing configuration-dependent clients.
    factory = cast(AgentFactory | None, request.app.state.agent_factory)
    if factory is not None:
        yield factory()
    else:
        with OpenAIResponsesClient() as client:
            yield ResearchAgent(
                registry=create_skill_registry(
                    LiveContextBuilder(request.app.state.research_config)
                ),
                llm=client,
            )


def get_report_workflow(
    request: Request, body: EquityResearchReportRequest
) -> Iterator[ReportWorkflowService]:
    # The validated shared body prevents configuration errors from masking bad input.
    factory = cast(AgentFactory | None, request.app.state.agent_factory)
    if factory is not None:
        yield ReportWorkflowService(factory())
    else:
        with live_agent(request.app.state.research_config) as agent:
            yield ReportWorkflowService(agent)
