"""Small EN/ZH presentation contract; never changes financial data or routing labels."""

import re

from financial_research.agent.errors import GroundingValidationError
from financial_research.schemas.agent import ResearchAgentRequest, ResponseLanguage, SynthesisOutput

_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_WORDS = re.compile(r"[A-Za-z_]+")
_FINANCIAL_WORDS = frozenset(
    {
        "fundamentals",
        "fundamental",
        "revenue",
        "profit",
        "income",
        "assets",
        "cash",
        "market",
        "stock",
        "price",
        "volatility",
        "data",
        "quality",
        "company",
        "profile",
        "performance",
        "financial",
        "equity",
        "net_income",
        "total_assets",
        "total_liabilities",
    }
)


def resolve_language(request: ResearchAgentRequest) -> tuple[ResponseLanguage, bool]:
    if request.response_language != ResponseLanguage.AUTO:
        return request.response_language, False
    han = len(_HAN.findall(request.question))
    words = [
        word
        for word in _WORDS.findall(request.question)
        if word.lower() not in _FINANCIAL_WORDS and not word.isupper()
    ]
    if han and han >= len(words):
        return ResponseLanguage.CHINESE, False
    if words:
        return ResponseLanguage.ENGLISH, False
    return ResponseLanguage.ENGLISH, True


def language_matches(text: str, language: ResponseLanguage) -> bool:
    """Conservative script check, not a claim of general linguistic fluency detection."""
    return (
        bool(_HAN.search(text)) if language == ResponseLanguage.CHINESE else not _HAN.search(text)
    )


def validate_response_language(output: SynthesisOutput, language: ResponseLanguage) -> None:
    if any(not language_matches(claim.statement, language) for claim in output.claims):
        raise GroundingValidationError("LANGUAGE_CONTRACT_VIOLATION")
