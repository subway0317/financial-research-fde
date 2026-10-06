"""Public deterministic functions and injected ticker/as-of facade."""

from financial_research.tools.company_snapshot import get_company_snapshot
from financial_research.tools.fundamental_trends import analyze_fundamental_trends
from financial_research.tools.market_behavior import summarize_market_behavior
from financial_research.tools.period_comparison import compare_periods
from financial_research.tools.research_quality import inspect_research_quality
from financial_research.tools.service import ResearchTools

__all__ = [
    "ResearchTools",
    "get_company_snapshot",
    "analyze_fundamental_trends",
    "compare_periods",
    "summarize_market_behavior",
    "inspect_research_quality",
]
