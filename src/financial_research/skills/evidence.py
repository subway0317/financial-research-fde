"""Deduplicate existing evidence IDs with explicit collision detection."""

from collections.abc import Iterable

from financial_research.schemas.tools import CalculationProvenance, EvidenceKind, EvidenceReference
from financial_research.skills.errors import EvidenceIntegrityError


def merge_evidence(*groups: Iterable[EvidenceReference]) -> dict[str, EvidenceReference]:
    index: dict[str, EvidenceReference] = {}
    for group in groups:
        for reference in group:
            previous = index.get(reference.evidence_id)
            if previous is not None and previous != reference:
                raise EvidenceIntegrityError("conflicting evidence content for one ID")
            index[reference.evidence_id] = reference
    return dict(sorted(index.items()))


def merge_calculations(
    *groups: Iterable[CalculationProvenance],
) -> tuple[CalculationProvenance, ...]:
    index: dict[str, CalculationProvenance] = {}
    for group in groups:
        for calculation in group:
            previous = index.get(calculation.evidence_id)
            if previous is not None and previous != calculation:
                raise EvidenceIntegrityError("conflicting calculation content for one ID")
            index[calculation.evidence_id] = calculation
    return tuple(index[key] for key in sorted(index))


def merge_limitations(*groups: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({reason for group in groups for reason in group}))


def validate_evidence(
    index: dict[str, EvidenceReference],
    calculations: tuple[CalculationProvenance, ...],
    referenced_ids: Iterable[str],
) -> None:
    if any(key != reference.evidence_id for key, reference in index.items()):
        raise EvidenceIntegrityError("evidence index identity mismatch")
    computed = {key for key, ref in index.items() if ref.kind == EvidenceKind.COMPUTATION}
    if {calc.evidence_id for calc in calculations} != computed:
        raise EvidenceIntegrityError("computation provenance is missing or orphaned")
    if not set(referenced_ids) <= index.keys():
        raise EvidenceIntegrityError("section evidence references do not resolve")
    for calc in calculations:
        if not calc.input_evidence_ids or not set(calc.input_evidence_ids) <= index.keys():
            raise EvidenceIntegrityError("calculation input evidence does not resolve")
