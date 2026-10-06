"""Descriptive market workflow over existing tool results, with no investment labels."""

from datetime import date

from financial_research.schemas.skills import (
    MarketAnalysisInput,
    MarketAnalysisResult,
    MarketAnalysisSection,
    SkillDefinition,
    SkillStatus,
)
from financial_research.schemas.tools import ResultStatus
from financial_research.skills.base import BaseSkill
from financial_research.skills.context import SkillExecutionContext
from financial_research.skills.evidence import merge_calculations, merge_evidence, merge_limitations


class MarketAnalysisSkill(BaseSkill[MarketAnalysisResult]):
    definition = SkillDefinition(
        skill_id="market_analysis",
        version="1.0",
        name="Market analysis",
        description="Organize descriptive observed-session market evidence and relative SMA state.",
        required_tools=("summarize_market_behavior",),
        input_type="financial_research.schemas.skills.MarketAnalysisInput",
        output_type="financial_research.schemas.skills.MarketAnalysisResult",
        capabilities=("descriptive_market_windows", "relative_sma_state"),
    )
    result_type = MarketAnalysisResult

    def run(
        self,
        *,
        ticker: str,
        as_of_date: date,
        lookback_sessions: int = 60,
    ) -> MarketAnalysisResult:
        request = MarketAnalysisInput(
            ticker=ticker, as_of_date=as_of_date, lookback_sessions=lookback_sessions
        )
        return self._run(
            request,
            lambda context: self.run_from_context(
                context, lookback_sessions=request.lookback_sessions
            ),
        )

    def run_from_context(
        self,
        execution: SkillExecutionContext,
        *,
        lookback_sessions: int = 60,
    ) -> MarketAnalysisResult:
        def organize() -> MarketAnalysisResult:
            market = execution.market(lookback_sessions)
            status = SkillStatus.SUCCESS
            if market.window.status == ResultStatus.UNAVAILABLE or market.latest_close is None:
                status = SkillStatus.UNAVAILABLE
            elif market.window.volatility_status == ResultStatus.UNAVAILABLE or any(
                value is None for value in market.latest_market_features.model_dump().values()
            ):
                status = SkillStatus.PARTIAL
            return MarketAnalysisResult(
                metadata=self.metadata(execution, status),
                market_analysis=MarketAnalysisSection(
                    latest_market_session=market.latest_market_session,
                    latest_close=market.latest_close,
                    window=market.window,
                    latest_market_features=market.latest_market_features,
                    evidence_ids=tuple(sorted(ref.evidence_id for ref in market.evidence)),
                ),
                evidence_index=merge_evidence(market.evidence),
                calculation_provenance=merge_calculations(market.calculation_provenance),
                limitations=merge_limitations(market.limitations),
                execution_trace=execution.trace(),
            )

        return self._execute(execution, organize)
