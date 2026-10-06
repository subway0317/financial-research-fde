"""Safe failures; provider messages and credentials never cross this boundary."""

from financial_research.exceptions import FinancialResearchError
from financial_research.schemas.agent import AgentExecutionTrace, LLMUsageMetadata


class AgentConfigurationError(FinancialResearchError):
    """Required LLM configuration is missing."""


class LLMProviderError(FinancialResearchError):
    """Transport, refusal or incomplete generation prevented structured output."""

    def __init__(self, message: str = "LLM provider failed.") -> None:
        super().__init__(message)
        self.usage: LLMUsageMetadata | None = None
        self.http_status: int | None = None
        self.trace: AgentExecutionTrace | None = None
        self.llm_usage: tuple[LLMUsageMetadata, ...] = ()


class LLMStructuredOutputError(LLMProviderError):
    """The response can be corrected once using a schema-only repair request."""
