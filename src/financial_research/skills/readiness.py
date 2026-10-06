"""Expose synthesis eligibility uniformly without changing existing workflow results."""

from financial_research.schemas.quality import QualityStatus
from financial_research.schemas.skills import (
    ResearchEvidencePackage,
    SkillResult,
    SkillStatus,
    SynthesisReadiness,
)


def synthesis_readiness(result: SkillResult) -> SynthesisReadiness:
    if isinstance(result, ResearchEvidencePackage):
        return result.synthesis_readiness
    if (
        result.metadata.status in {SkillStatus.FAILED, SkillStatus.UNAVAILABLE}
        or result.metadata.quality is None
        or result.metadata.quality.status == QualityStatus.FAIL
    ):
        return SynthesisReadiness.NOT_READY
    if (
        result.metadata.status == SkillStatus.PARTIAL
        or result.metadata.quality.status == QualityStatus.PASS_WITH_WARNINGS
        or result.limitations
    ):
        return SynthesisReadiness.READY_WITH_WARNINGS
    return SynthesisReadiness.READY
