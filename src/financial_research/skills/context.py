"""One bounded execution owns research state and typed in-memory tool results."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from financial_research.exceptions import DataValidationError
from financial_research.schemas.research import ResearchContext
from financial_research.schemas.skills import (
    SkillExecutionTrace,
    SkillInput,
    SkillStatus,
    SkillTraceStep,
    TraceAction,
)
from financial_research.schemas.tools import (
    CalculationProvenance,
    CompanySnapshotResult,
    EvidenceReference,
    FundamentalTrendResult,
    MarketBehaviorResult,
    ResearchQualityResult,
)
from financial_research.skills.errors import safe_error
from financial_research.skills.evidence import merge_calculations, merge_evidence, merge_limitations
from financial_research.tools import (
    analyze_fundamental_trends,
    get_company_snapshot,
    inspect_research_quality,
    summarize_market_behavior,
)
from financial_research.tools.common import (
    context_limitations,
    metric_names,
    validate_context,
    validate_lookback,
)
from financial_research.tools.market_behavior import summarize_window
from financial_research.tools.service import ContextBuilder


@dataclass
class SkillExecutionContext:
    ticker: str
    as_of_date: date
    execution_id: UUID = field(default_factory=uuid4)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    research_context: ResearchContext | None = None
    _steps: list[SkillTraceStep] = field(default_factory=list, init=False, repr=False)
    _snapshot: CompanySnapshotResult | None = field(default=None, init=False, repr=False)
    _trends: dict[tuple[str, ...], FundamentalTrendResult] = field(
        default_factory=dict, init=False, repr=False
    )
    _markets: dict[int, MarketBehaviorResult] = field(default_factory=dict, init=False, repr=False)
    _quality: ResearchQualityResult | None = field(default=None, init=False, repr=False)
    _bound_context: ResearchContext | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        request = SkillInput(ticker=self.ticker, as_of_date=self.as_of_date)
        self.ticker = request.ticker
        self.as_of_date = request.as_of_date
        if self.execution_id.version != 4 or self.generated_at.utcoffset() is None:
            raise DataValidationError("execution requires UUID4 and aware timestamp")

    def record(
        self,
        action: TraceAction,
        target: str,
        status: SkillStatus,
        *,
        duration_ms: float | None = None,
        error_code: str | None = None,
    ) -> None:
        self._steps.append(
            SkillTraceStep(
                sequence=len(self._steps) + 1,
                action_type=action,
                target=target,
                status=status,
                duration_ms=duration_ms,
                error_code=error_code,
                quality_status=self.research_context.quality.status
                if self.research_context
                else None,
            )
        )

    def trace(self) -> SkillExecutionTrace:
        return SkillExecutionTrace(steps=tuple(self._steps))

    def require_context(self) -> ResearchContext:
        if self.research_context is None:
            raise DataValidationError("execution has no acquired ResearchContext")
        if self._bound_context is not None and self.research_context is not self._bound_context:
            raise DataValidationError("research state cannot change within an execution")
        if (self.research_context.ticker, self.research_context.as_of_date) != (
            self.ticker,
            self.as_of_date,
        ):
            raise DataValidationError("execution identity disagrees with ResearchContext")
        validate_context(self.research_context, allow_failed_quality=True)
        self._bound_context = self.research_context
        return self.research_context

    def acquire(self, builder: ContextBuilder) -> None:
        if self.research_context is not None:
            self.call(TraceAction.CONTEXT_REUSE, "research_context", self.require_context)
            return

        def build() -> ResearchContext:
            self.research_context = builder.build(ticker=self.ticker, as_of_date=self.as_of_date)
            return self.require_context()

        self.call(TraceAction.CONTEXT_BUILD, "research_context", build)

    def call[T](self, action: TraceAction, target: str, operation: Callable[[], T]) -> T:
        started = time.perf_counter()
        try:
            result = operation()
        except Exception as exc:
            self.record(
                action,
                target,
                SkillStatus.FAILED,
                duration_ms=(time.perf_counter() - started) * 1000,
                error_code=safe_error(exc, target).error_code,
            )
            raise
        self.record(
            action, target, SkillStatus.SUCCESS, duration_ms=(time.perf_counter() - started) * 1000
        )
        return result

    def snapshot(self) -> CompanySnapshotResult:
        if self._snapshot is None:
            self._snapshot = self.call(
                TraceAction.TOOL_CALL,
                "get_company_snapshot",
                lambda: get_company_snapshot(self.require_context()),
            )
        else:
            self.record(TraceAction.TOOL_REUSE, "get_company_snapshot", SkillStatus.SUCCESS)
        return self._snapshot

    def trends(self, metrics: list[str] | None) -> FundamentalTrendResult:
        key = metric_names(metrics)
        if key not in self._trends:
            self._trends[key] = self.call(
                TraceAction.TOOL_CALL,
                "analyze_fundamental_trends",
                lambda: analyze_fundamental_trends(self.require_context(), metrics=metrics),
            )
        else:
            self.record(TraceAction.TOOL_REUSE, "analyze_fundamental_trends", SkillStatus.SUCCESS)
        return self._trends[key]

    def market(self, sessions: int) -> MarketBehaviorResult:
        validate_lookback(sessions)
        if sessions not in self._markets and self._snapshot is not None:
            snapshot = self._snapshot
            window = next(
                (w for w in snapshot.market_windows if w.lookback_sessions_requested == sessions),
                None,
            )
            standard_window = window is not None
            window_evidence: tuple[EvidenceReference, ...] = ()
            window_calculations: tuple[CalculationProvenance, ...] = ()
            if window is None:
                window, window_evidence, window_calculations = self.call(
                    TraceAction.TOOL_CALL,
                    "summarize_market_behavior.window",
                    lambda: summarize_window(self.require_context(), sessions),
                )
            if window is not None:
                calculations = tuple(
                    calc
                    for calc in snapshot.calculation_provenance
                    if calc.calculation_name
                    in {"close_to_sma_5", "close_to_sma_20", "close_to_sma_60"}
                    or standard_window
                    and any(
                        p.name == "lookback_sessions" and p.value == sessions
                        for p in calc.parameters
                    )
                )
                calculations = merge_calculations(calculations, window_calculations)
                ids = {
                    identifier
                    for calc in calculations
                    for identifier in (calc.evidence_id, *calc.input_evidence_ids)
                }
                ids.update(
                    ref.evidence_id
                    for ref in snapshot.evidence
                    if ref.metric == "close" and ref.date == snapshot.latest_market_session
                )
                self._markets[sessions] = MarketBehaviorResult(
                    ticker=snapshot.ticker,
                    as_of_date=snapshot.as_of_date,
                    quality=snapshot.quality,
                    latest_market_session=snapshot.latest_market_session,
                    latest_close=snapshot.latest_close,
                    window=window,
                    latest_market_features=snapshot.latest_market_features,
                    evidence=tuple(
                        merge_evidence(
                            (ref for ref in snapshot.evidence if ref.evidence_id in ids),
                            window_evidence,
                        ).values()
                    ),
                    calculation_provenance=calculations,
                    limitations=merge_limitations(
                        context_limitations(self.require_context()), window.limitations
                    ),
                )
                self.record(
                    TraceAction.TOOL_REUSE,
                    f"get_company_snapshot.market_window_{sessions}"
                    if standard_window
                    else "get_company_snapshot.relative_sma",
                    SkillStatus.SUCCESS,
                )
                return self._markets[sessions]
        if sessions not in self._markets:
            self._markets[sessions] = self.call(
                TraceAction.TOOL_CALL,
                "summarize_market_behavior",
                lambda: summarize_market_behavior(
                    self.require_context(), lookback_sessions=sessions
                ),
            )
        else:
            self.record(TraceAction.TOOL_REUSE, "summarize_market_behavior", SkillStatus.SUCCESS)
        return self._markets[sessions]

    def quality(self) -> ResearchQualityResult:
        if self._quality is None:
            self._quality = self.call(
                TraceAction.TOOL_CALL,
                "inspect_research_quality",
                lambda: inspect_research_quality(self.require_context()),
            )
        else:
            self.record(TraceAction.TOOL_REUSE, "inspect_research_quality", SkillStatus.SUCCESS)
        return self._quality
