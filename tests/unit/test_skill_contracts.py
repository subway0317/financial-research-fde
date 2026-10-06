from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from financial_research.exceptions import DataValidationError
from financial_research.schemas.quality import QualityIssue, QualityReport, QualityStatus, Severity
from financial_research.schemas.skills import (
    ResearchEvidencePackage,
    SkillDefinition,
    SkillExecutionTrace,
    SkillResultMetadata,
    SkillStatus,
    SkillTraceStep,
    SynthesisReadiness,
    TraceAction,
)
from financial_research.skills import SkillExecutionContext, SkillRegistry
from financial_research.skills.errors import EvidenceIntegrityError
from financial_research.skills.evidence import merge_calculations, merge_evidence, merge_limitations
from financial_research.tools import compare_periods


def definition() -> SkillDefinition:
    return SkillDefinition(
        skill_id="fixture_skill",
        version="1.0",
        name="Fixture skill",
        description="Organize existing research evidence.",
        required_tools=("compare_periods",),
        input_type="financial_research.schemas.skills.SkillInput",
        output_type="financial_research.schemas.skills.SkillResult",
        capabilities=("evidence_organization",),
    )


@pytest.mark.parametrize(
    "update",
    [
        {"skill_id": "invalid id"},
        {"version": "latest"},
        {"description": ""},
        {"required_tools": ("same", "same")},
        {"capabilities": ()},
    ],
)
def test_definition_rejects_unstable_metadata(update) -> None:
    with pytest.raises(ValidationError):
        SkillDefinition.model_validate({**definition().model_dump(), **update})


def test_explicit_registry_lookup_sorted_listing_and_duplicate_rejection() -> None:
    class Stub:
        def __init__(self, metadata):
            self.definition = metadata

        def run(self, **kwargs):
            raise NotImplementedError

        def run_from_context(self, execution):
            raise NotImplementedError

    registry = SkillRegistry()
    first = Stub(definition())
    registry.register(first)
    registry.register(Stub(definition().model_copy(update={"skill_id": "another_skill"})))
    assert registry.get("fixture_skill") is first
    assert [item.skill_id for item in registry.list()] == ["another_skill", "fixture_skill"]
    with pytest.raises(DataValidationError):
        registry.register(first)
    with pytest.raises(KeyError):
        registry.get("unknown")


def test_quality_and_skill_status_remain_distinct() -> None:
    warnings = QualityReport.from_issues(
        (QualityIssue(code="VINTAGE", severity=Severity.WARNING, message="Retrieved vintage."),)
    )
    metadata = SkillResultMetadata(
        skill_id="fixture_skill",
        skill_version="1.0",
        ticker="NVDA",
        as_of_date=date(2025, 5, 25),
        execution_id=uuid4(),
        generated_at=datetime.now(UTC),
        status=SkillStatus.SUCCESS,
        quality=warnings,
    )
    assert metadata.status == SkillStatus.SUCCESS
    assert metadata.quality.status == QualityStatus.PASS_WITH_WARNINGS
    failed_quality = QualityReport.from_issues(
        (QualityIssue(code="INTEGRITY", severity=Severity.ERROR, message="Invalid evidence."),)
    )
    with pytest.raises(ValidationError):
        SkillResultMetadata.model_validate({**metadata.model_dump(), "quality": failed_quality})


def test_context_reuses_identity_without_calling_builder(fiscal_context) -> None:
    class NeverBuild:
        def build(self, **kwargs):
            raise AssertionError("must reuse supplied research state")

    execution = SkillExecutionContext(
        ticker="nvda",
        as_of_date=fiscal_context.as_of_date,
        research_context=fiscal_context,
    )
    execution.acquire(NeverBuild())
    assert execution.require_context() is fiscal_context
    assert execution.execution_id.version == 4
    assert execution.trace().steps[0].action_type == TraceAction.CONTEXT_REUSE
    execution.ticker = "OTHER"
    with pytest.raises(DataValidationError):
        execution.require_context()


def test_evidence_and_calculations_deduplicate_and_detect_collision(fiscal_context) -> None:
    tool = compare_periods(fiscal_context, metric="revenue")
    index = merge_evidence(tool.evidence, reversed(tool.evidence))
    assert len(index) == len(tool.evidence)
    assert list(index) == sorted(index)
    altered = tool.evidence[0].model_copy(update={"value": "999"})
    with pytest.raises(EvidenceIntegrityError):
        merge_evidence(tool.evidence, (altered,))
    calculations = merge_calculations(tool.calculation_provenance, tool.calculation_provenance)
    assert len(calculations) == len(tool.calculation_provenance)
    altered_calculation = calculations[0].model_copy(update={"formula": "invalid"})
    with pytest.raises(EvidenceIntegrityError):
        merge_calculations(calculations, (altered_calculation,))
    assert merge_limitations(("B", "A"), ("A", "C")) == ("A", "B", "C")


def test_trace_has_only_objective_fields_and_contiguous_sequence() -> None:
    step = SkillTraceStep(
        sequence=1,
        action_type=TraceAction.QUALITY_GATE,
        target="research_context",
        status=SkillStatus.SUCCESS,
    )
    SkillExecutionTrace(steps=(step,))
    with pytest.raises(ValidationError):
        SkillTraceStep.model_validate({**step.model_dump(), "reasoning": "internal thought"})
    with pytest.raises(ValidationError):
        SkillExecutionTrace(steps=(step.model_copy(update={"sequence": 2}),))


def test_failed_package_cannot_be_ready() -> None:
    metadata = SkillResultMetadata(
        skill_id="equity_research",
        skill_version="1.0",
        ticker="NVDA",
        as_of_date=date(2025, 5, 25),
        execution_id=uuid4(),
        generated_at=datetime.now(UTC),
        status=SkillStatus.FAILED,
    )
    with pytest.raises(ValidationError):
        ResearchEvidencePackage(
            metadata=metadata,
            synthesis_readiness=SynthesisReadiness.READY,
            execution_trace=SkillExecutionTrace(),
        )
