"""Five explicitly registered local capabilities; construction performs no I/O."""

from financial_research.skills.company_overview import CompanyOverviewSkill
from financial_research.skills.equity_research import EquityResearchSkill
from financial_research.skills.fundamental_analysis import FundamentalAnalysisSkill
from financial_research.skills.market_analysis import MarketAnalysisSkill
from financial_research.skills.registry import SkillRegistry
from financial_research.skills.research_quality import ResearchQualityAuditSkill
from financial_research.tools.service import ContextBuilder


def create_skill_registry(builder: ContextBuilder | None = None) -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(CompanyOverviewSkill(builder))
    registry.register(FundamentalAnalysisSkill(builder))
    registry.register(MarketAnalysisSkill(builder))
    registry.register(ResearchQualityAuditSkill(builder))
    registry.register(EquityResearchSkill(builder))
    return registry
