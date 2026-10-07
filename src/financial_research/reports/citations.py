"""Stable aliases for cited evidence and its complete transitive calculation inputs."""

from financial_research.reports.errors import ReportCompilationError
from financial_research.reports.schemas import CalculationAppendixEntry, EvidenceAppendixEntry
from financial_research.schemas.agent import GroundedResearchAnswer
from financial_research.schemas.tools import EvidenceKind


def appendices(
    answer: GroundedResearchAnswer,
) -> tuple[tuple[EvidenceAppendixEntry, ...], tuple[CalculationAppendixEntry, ...]]:
    calculations = {calc.evidence_id: calc for calc in answer.calculation_provenance}
    if len(calculations) != len(answer.calculation_provenance):
        raise ReportCompilationError("DUPLICATE_CALCULATION_ID")
    referenced = {key for claim in answer.claims for key in claim.evidence_ids}
    pending = list(referenced)
    while pending:
        key = pending.pop()
        reference = answer.citations.get(key)
        if reference is None or reference.evidence_id != key:
            raise ReportCompilationError("UNRESOLVED_EVIDENCE")
        if reference.kind == EvidenceKind.COMPUTATION:
            calc = calculations.get(key)
            if calc is None or not calc.input_evidence_ids:
                raise ReportCompilationError("MISSING_CALCULATION_INPUTS")
            for input_id in calc.input_evidence_ids:
                if input_id not in referenced:
                    referenced.add(input_id)
                    pending.append(input_id)
    aliases = {key: f"E{number}" for number, key in enumerate(sorted(referenced), 1)}
    evidence = tuple(
        EvidenceAppendixEntry(display_alias=alias, canonical_id=key, evidence=answer.citations[key])
        for key, alias in aliases.items()
    )
    computed = sorted(
        key for key in referenced if answer.citations[key].kind == EvidenceKind.COMPUTATION
    )
    calculation_entries = []
    for number, key in enumerate(computed, 1):
        reference, calc = answer.citations[key], calculations[key]
        calculation_entries.append(
            CalculationAppendixEntry(
                display_alias=f"C{number}",
                canonical_id=key,
                provenance=calc,
                result=reference.value,
                result_unit=reference.unit,
                date=reference.date,
                period_start=reference.period_start,
                period_end=reference.period_end,
                input_display_aliases=tuple(aliases[key] for key in calc.input_evidence_ids),
            )
        )
    return evidence, tuple(calculation_entries)
