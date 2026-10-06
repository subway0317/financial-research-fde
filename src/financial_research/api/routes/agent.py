"""Thin stateless transport for the Stage 4 research service."""

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from financial_research.agent.service import ResearchAgent
from financial_research.api.dependencies import get_research_agent
from financial_research.api.errors import request_id
from financial_research.api.schemas import AgentResearchEnvelope, AgentResearchRequest
from financial_research.schemas.agent import ResearchAgentRequest

router = APIRouter(prefix="/v1/agent", tags=["agent"])
logger = logging.getLogger(__name__)


@router.post("/research", response_model=AgentResearchEnvelope)
def research(
    body: AgentResearchRequest,
    request: Request,
    agent: Annotated[ResearchAgent, Depends(get_research_agent)],
) -> AgentResearchEnvelope:
    result = agent.run(ResearchAgentRequest.model_validate(body.model_dump()))
    logger.info(
        "agent request request_id=%s ticker=%s as_of_date=%s skill=%s status=%s readiness=%s "
        "llm_calls=%d",
        request_id(request),
        body.ticker,
        body.as_of_date,
        result.plan.selected_skill_id,
        result.agent_status,
        result.synthesis_readiness,
        len(result.llm_usage),
    )
    return AgentResearchEnvelope(
        request_id=request_id(request),
        generated_at=datetime.now(UTC),
        data=result,
        quality=result.quality,
        limitations=result.limitations,
    )
