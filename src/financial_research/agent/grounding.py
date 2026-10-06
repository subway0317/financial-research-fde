"""Enforce supplied citations, claim categories and executed-skill identity."""

from financial_research.agent.errors import AgentIntegrityError, GroundingValidationError
from financial_research.agent.policy import validate_research_policy
from financial_research.schemas.agent import (
    ClaimType,
    EvidenceProjection,
    GroundedResearchAnswer,
    SynthesisOutput,
)
from financial_research.schemas.skills import SynthesisReadiness
from financial_research.schemas.tools import EvidenceKind


def validate_grounding(output: SynthesisOutput, projection: EvidenceProjection) -> None:
    if projection.synthesis_readiness == SynthesisReadiness.NOT_READY:
        raise GroundingValidationError("NOT_READY_SYNTHESIS")
    if output.used_skill_ids != (projection.skill_id,):
        raise GroundingValidationError("EXECUTED_SKILL_MISMATCH")
    if len({claim.claim_id for claim in output.claims}) != len(output.claims):
        raise GroundingValidationError("DUPLICATE_CLAIM_ID")
    for claim in output.claims:
        if not set(claim.evidence_ids) <= projection.evidence_index.keys():
            raise GroundingValidationError("UNKNOWN_CITATION")
        kinds = {projection.evidence_index[key].kind for key in claim.evidence_ids}
        if claim.claim_type == ClaimType.COMPUTED_FACT and EvidenceKind.COMPUTATION not in kinds:
            raise GroundingValidationError("COMPUTED_CLAIM_WITHOUT_COMPUTATION")
        if claim.claim_type == ClaimType.SOURCE_FACT and EvidenceKind.SOURCE_FACT not in kinds:
            raise GroundingValidationError("SOURCE_CLAIM_WITHOUT_SOURCE")
        validate_research_policy(claim.statement)


def validate_final_answer(answer: GroundedResearchAnswer, projection: EvidenceProjection) -> None:
    if not set(projection.limitations) <= set(answer.limitations):
        raise AgentIntegrityError("MANDATORY_LIMITATIONS_LOST")
    if (
        answer.quality != projection.quality
        or answer.synthesis_readiness != projection.synthesis_readiness
    ):
        raise AgentIntegrityError("AUTHORITATIVE_QUALITY_CHANGED")
    if (
        answer.citations != projection.evidence_index
        or answer.calculation_provenance != projection.calculation_provenance
    ):
        raise AgentIntegrityError("ANSWER_PROVENANCE_CHANGED")
    validate_grounding(
        SynthesisOutput(claims=answer.claims, used_skill_ids=answer.used_skill_ids), projection
    )
