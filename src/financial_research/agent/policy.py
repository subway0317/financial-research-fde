"""Deliberately narrow policy for explicit recommendations, predictions and trade commands."""

import re

from financial_research.agent.errors import GroundingValidationError

_PROHIBITED = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:buy|sell|short)\s+(?:[A-Z]{1,10}\b|(?:the |these )?(?:stock|shares)\b)",
        r"\b(?:a|strong)\s+(?:buy|sell)\b",
        r"\b(?:target\s+price|price\s+target|expected\s+returns?)\b",
        r"\b(?:stock|shares?|price|[A-Z]{1,10})\s+(?:will|is going to)\s+"
        r"(?:rise|fall|increase|decrease|reach)\b",
        r"\b(?:place|execute)\s+(?:a |an )?(?:trade|order)\b",
        r"\b(?:买入|卖出|目标价|预期收益)\b",
        r"(?:建议|应该|应当|推荐|现在|立即|请)\s*(?:买入|卖出|购买|卖掉|做空)",
        r"(?:买入|卖出|做空)\s*[A-Z]{1,10}\b",
        r"(?:目标价|预期收益)",
        r"(?:股价|股票|价格).{0,8}(?:将会|将|必然)(?:上涨|下跌|达到)",
    )
)


def validate_research_policy(statement: str) -> None:
    if any(pattern.search(statement) for pattern in _PROHIBITED):
        raise GroundingValidationError("PROHIBITED_RECOMMENDATION")
