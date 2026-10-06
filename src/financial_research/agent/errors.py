"""Typed integrity failures with code-only diagnostics and objective execution metadata."""

from financial_research.exceptions import FinancialResearchError
from financial_research.schemas.agent import AgentExecutionTrace, LLMUsageMetadata


class AgentIntegrityError(FinancialResearchError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.trace: AgentExecutionTrace | None = None
        self.llm_usage: tuple[LLMUsageMetadata, ...] = ()


class AgentPlanValidationError(AgentIntegrityError):
    """The planner schema or registered routing contract was violated."""


class GroundingValidationError(AgentIntegrityError):
    """Synthesis failed citation, output schema or recommendation validation."""


class PayloadBudgetExceeded(AgentIntegrityError):
    """No synthesis request is sent when its serialized input exceeds the ceiling."""

    def __init__(self, *, actual_bytes: int, budget_bytes: int) -> None:
        super().__init__("SYNTHESIS_PAYLOAD_BUDGET_EXCEEDED")
        self.actual_bytes = actual_bytes
        self.budget_bytes = budget_bytes
