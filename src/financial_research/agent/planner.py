"""Registry-derived capabilities and the deterministic routing allowlist."""

from financial_research.agent.errors import AgentPlanValidationError
from financial_research.schemas.agent import (
    AgentIntent,
    AgentPlan,
    AgentReasonCode,
    ResearchAgentRequest,
    SkillCapability,
)
from financial_research.skills.registry import SkillRegistry

INTENT_SKILLS = {
    AgentIntent.COMPANY_OVERVIEW: "company_overview",
    AgentIntent.FUNDAMENTAL_FOCUS: "fundamental_analysis",
    AgentIntent.MARKET_FOCUS: "market_analysis",
    AgentIntent.QUALITY_FOCUS: "research_quality_audit",
    AgentIntent.BROAD_RESEARCH: "equity_research",
}
INTENT_REASONS = {
    AgentIntent.COMPANY_OVERVIEW: AgentReasonCode.COMPANY_INFORMATION_REQUEST,
    AgentIntent.FUNDAMENTAL_FOCUS: AgentReasonCode.FUNDAMENTAL_ANALYSIS_REQUEST,
    AgentIntent.MARKET_FOCUS: AgentReasonCode.MARKET_ANALYSIS_REQUEST,
    AgentIntent.QUALITY_FOCUS: AgentReasonCode.DATA_QUALITY_REQUEST,
    AgentIntent.BROAD_RESEARCH: AgentReasonCode.BROAD_EQUITY_RESEARCH_REQUEST,
}


def capability_manifest(registry: SkillRegistry) -> tuple[SkillCapability, ...]:
    return tuple(
        SkillCapability(
            skill_id=definition.skill_id,
            name=definition.name,
            description=definition.description,
            capabilities=definition.capabilities,
            input_type=definition.input_type,
        )
        for definition in registry.list()
    )


def validate_plan(plan: AgentPlan, request: ResearchAgentRequest, registry: SkillRegistry) -> None:
    if plan.selected_skill_id not in {definition.skill_id for definition in registry.list()}:
        raise AgentPlanValidationError("UNREGISTERED_SKILL")
    if plan.selected_skill_id != INTENT_SKILLS[plan.intent]:
        raise AgentPlanValidationError("INTENT_SKILL_MISMATCH")
    if plan.reason_code != INTENT_REASONS[plan.intent]:
        raise AgentPlanValidationError("INTENT_REASON_MISMATCH")
    if (plan.ticker, plan.as_of_date) != (request.ticker, request.as_of_date):
        raise AgentPlanValidationError("REQUEST_IDENTITY_CHANGED")
