"""Small execution boundary: typed failures and objective action records."""

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable

from financial_research.research.live import LiveContextBuilder
from financial_research.schemas.quality import QualityStatus
from financial_research.schemas.skills import (
    SkillDefinition,
    SkillErrorMetadata,
    SkillInput,
    SkillResult,
    SkillResultMetadata,
    SkillStatus,
    TraceAction,
)
from financial_research.skills.context import SkillExecutionContext
from financial_research.skills.errors import CriticalQualityError, safe_error
from financial_research.skills.evidence import merge_limitations
from financial_research.tools.common import context_limitations
from financial_research.tools.service import ContextBuilder

logger = logging.getLogger(__name__)


class BaseSkill[R: SkillResult](ABC):
    definition: SkillDefinition
    result_type: type[R]
    allows_failed_quality = False

    def __init__(self, builder: ContextBuilder | None = None) -> None:
        self._builder = builder

    @abstractmethod
    def run_from_context(self, execution: SkillExecutionContext) -> R: ...

    def metadata(
        self,
        execution: SkillExecutionContext,
        status: SkillStatus,
        error: SkillErrorMetadata | None = None,
    ) -> SkillResultMetadata:
        return SkillResultMetadata(
            skill_id=self.definition.skill_id,
            skill_version=self.definition.version,
            ticker=execution.ticker,
            as_of_date=execution.as_of_date,
            execution_id=execution.execution_id,
            generated_at=execution.generated_at,
            status=status,
            quality=execution.research_context.quality if execution.research_context else None,
            error=error,
        )

    def _failed(self, execution: SkillExecutionContext, exc: Exception) -> R:
        error = safe_error(exc, self.definition.skill_id)
        limitations = (
            context_limitations(execution.research_context) if execution.research_context else ()
        )
        logger.error(
            "skill failure execution_id=%s skill_id=%s error_code=%s",
            execution.execution_id,
            self.definition.skill_id,
            error.error_code,
        )
        return self.result_type(
            metadata=self.metadata(execution, SkillStatus.FAILED, error),
            limitations=merge_limitations(limitations, (error.error_code,)),
            execution_trace=execution.trace(),
        )

    def _run(
        self,
        request: SkillInput,
        operation: Callable[[SkillExecutionContext], R],
        *,
        preflight: Callable[[], object] | None = None,
    ) -> R:
        execution = SkillExecutionContext(ticker=request.ticker, as_of_date=request.as_of_date)
        try:
            if preflight is not None:
                preflight()
            execution.acquire(self._builder if self._builder is not None else LiveContextBuilder())
        except Exception as exc:
            execution.record(
                TraceAction.SKILL_CALL,
                self.definition.skill_id,
                SkillStatus.FAILED,
                error_code=safe_error(exc, self.definition.skill_id).error_code,
            )
            return self._failed(execution, exc)
        return operation(execution)

    def _execute(self, execution: SkillExecutionContext, operation: Callable[[], R]) -> R:
        started = time.perf_counter()
        try:
            context = (
                execution.call(
                    TraceAction.CONTEXT_REUSE, "research_context", execution.require_context
                )
                if not execution.trace().steps
                else execution.require_context()
            )
            if context.quality.status == QualityStatus.FAIL and not self.allows_failed_quality:
                raise CriticalQualityError()
            result = operation()
        except Exception as exc:
            execution.record(
                TraceAction.SKILL_CALL,
                self.definition.skill_id,
                SkillStatus.FAILED,
                duration_ms=(time.perf_counter() - started) * 1000,
                error_code=safe_error(exc, self.definition.skill_id).error_code,
            )
            return self._failed(execution, exc)
        execution.record(
            TraceAction.SKILL_CALL,
            self.definition.skill_id,
            result.metadata.status,
            duration_ms=(time.perf_counter() - started) * 1000,
            error_code=result.metadata.error.error_code if result.metadata.error else None,
        )
        logger.info(
            "skill result execution_id=%s skill_id=%s status=%s",
            execution.execution_id,
            self.definition.skill_id,
            result.metadata.status,
        )
        return result.model_copy(update={"execution_trace": execution.trace()})
