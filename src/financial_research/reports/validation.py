"""Structural, PIT and cross-file integrity checks; no semantic judging or recalculation."""

import re
from pathlib import Path

from pydantic import ValidationError

from financial_research.reports.errors import ReportIntegrityError
from financial_research.reports.identity import semantic_hash, sha256
from financial_research.reports.manifest import build_manifest, evidence_artifact
from financial_research.reports.rendering import render_markdown
from financial_research.reports.schemas import (
    ReportEvidenceArtifact,
    ReportFileHashes,
    ReportManifest,
    ReportSectionID,
    ReportStatus,
    ResearchReport,
)
from financial_research.schemas.agent import AgentTraceAction, LLMPhase
from financial_research.schemas.quality import QualityStatus
from financial_research.schemas.skills import SynthesisReadiness
from financial_research.schemas.tools import EvidenceKind


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ReportIntegrityError(code)


def validate_report(report: ResearchReport) -> None:
    try:
        report = ResearchReport.model_validate(report.model_dump())
    except ValidationError:
        raise ReportIntegrityError("INVALID_REPORT_SCHEMA") from None
    digest = semantic_hash(report)
    _require(
        report.report_id == f"report:{digest}" and report.integrity.semantic_hash == digest,
        "REPORT_ID_MISMATCH",
    )
    expected_sections = tuple(
        section
        for section in ReportSectionID
        if report.status != ReportStatus.BLOCKED
        or section
        not in {ReportSectionID.COMPANY, ReportSectionID.FUNDAMENTALS, ReportSectionID.MARKET}
    )
    _require(tuple(s.section_id for s in report.sections) == expected_sections, "SECTION_ORDER")
    claims = tuple(claim for section in report.sections for claim in section.claims)
    _require(len({claim.claim_id for claim in claims}) == len(claims), "DUPLICATE_CLAIM_ID")
    _require(
        all(
            claim.section.value == section.section_id.value
            for section in report.sections
            for claim in section.claims
        ),
        "CLAIM_SECTION_MISMATCH",
    )
    _require(report.quality_status == report.quality.status, "QUALITY_MISMATCH")
    runtime = report.runtime_metadata
    usage = runtime.llm_usage
    _require(
        all(u.phase in {LLMPhase.SYNTHESIS, LLMPhase.SYNTHESIS_REPAIR} for u in usage)
        and len(usage) == runtime.synthesis_call_count
        and sum(u.repair_count for u in usage) == runtime.repair_count,
        "LLM_BUDGET_MISMATCH",
    )
    _require(
        not any(step.action == AgentTraceAction.PLAN_REQUEST for step in runtime.trace.steps)
        and sum(step.action == AgentTraceAction.SYNTHESIS_REQUEST for step in runtime.trace.steps)
        == len(usage),
        "TRACE_BUDGET_MISMATCH",
    )
    if report.status == ReportStatus.BLOCKED:
        _require(
            report.synthesis_readiness == SynthesisReadiness.NOT_READY
            and not claims
            and not usage
            and bool(report.blocking_reasons),
            "INVALID_BLOCKED_REPORT",
        )
    else:
        _require(
            bool(claims)
            and report.synthesis_readiness != SynthesisReadiness.NOT_READY
            and report.quality_status != QualityStatus.FAIL
            and 1 <= len(usage) <= 2
            and usage[0].phase == LLMPhase.SYNTHESIS
            and usage[0].repair_count == 0
            and usage[-1].success
            and (
                len(usage) == 1
                or (
                    usage[1].phase == LLMPhase.SYNTHESIS_REPAIR
                    and usage[1].repair_count == 1
                    and not usage[0].success
                )
            ),
            "INVALID_COMPLETED_REPORT",
        )
        expected_status = (
            ReportStatus.COMPLETED
            if report.synthesis_readiness == SynthesisReadiness.READY
            else ReportStatus.COMPLETED_WITH_WARNINGS
        )
        _require(report.status == expected_status, "STATUS_READINESS_MISMATCH")
    entries = report.evidence_appendix
    evidence = {entry.canonical_id: entry.evidence for entry in entries}
    aliases = {entry.canonical_id: entry.display_alias for entry in entries}
    _require(len(evidence) == len(entries), "DUPLICATE_EVIDENCE_ID")
    _require(
        [entry.canonical_id for entry in entries] == sorted(evidence)
        and [entry.display_alias for entry in entries]
        == [f"E{n}" for n in range(1, len(entries) + 1)]
        and all(key == ref.evidence_id for key, ref in evidence.items()),
        "INVALID_EVIDENCE_ALIASES",
    )
    _require(
        all(set(claim.evidence_ids) <= evidence.keys() for claim in claims), "UNKNOWN_CITATION"
    )
    for reference in evidence.values():
        _require(
            all(
                value is None or value <= report.as_of_date
                for value in (
                    reference.date,
                    reference.period_start,
                    reference.period_end,
                    reference.filed_at,
                    reference.available_date,
                )
            ),
            "PIT_VIOLATION",
        )
        if reference.filed_at is not None and reference.available_date is not None:
            _require(reference.filed_at < reference.available_date, "PIT_AVAILABILITY_ORDER")
    calculations = {entry.canonical_id: entry for entry in report.calculation_appendix}
    computed = {key for key, ref in evidence.items() if ref.kind == EvidenceKind.COMPUTATION}
    _require(
        len(calculations) == len(report.calculation_appendix) and set(calculations) == computed,
        "CALCULATION_ID_MISMATCH",
    )
    _require(
        [entry.canonical_id for entry in report.calculation_appendix] == sorted(computed)
        and [entry.display_alias for entry in report.calculation_appendix]
        == [f"C{n}" for n in range(1, len(calculations) + 1)],
        "INVALID_CALCULATION_ALIASES",
    )
    for key, entry in calculations.items():
        provenance, reference = entry.provenance, evidence[key]
        _require(
            provenance.evidence_id == key
            and bool(provenance.input_evidence_ids)
            and set(provenance.input_evidence_ids) <= evidence.keys(),
            "UNKNOWN_CALCULATION_INPUT",
        )
        _require(
            entry.input_display_aliases
            == tuple(aliases[key] for key in provenance.input_evidence_ids),
            "CALCULATION_INPUT_ALIAS_MISMATCH",
        )
        _require(
            (entry.result, entry.result_unit, entry.date, entry.period_start, entry.period_end)
            == (
                reference.value,
                reference.unit,
                reference.date,
                reference.period_start,
                reference.period_end,
            ),
            "CALCULATION_RESULT_CHANGED",
        )
    # Iterative traversal checks both exact relevance and acyclic computation dependencies.
    reached: set[str] = set()
    active: set[str] = set()
    for root in (key for claim in claims for key in claim.evidence_ids):
        stack = [(root, False)]
        while stack:
            key, finishing = stack.pop()
            if finishing:
                active.remove(key)
                reached.add(key)
                continue
            _require(key not in active, "CYCLIC_CALCULATION")
            if key in reached:
                continue
            active.add(key)
            stack.append((key, True))
            if key in calculations:
                stack.extend(
                    (item, False) for item in calculations[key].provenance.input_evidence_ids
                )
    _require(reached == set(evidence), "UNRELATED_EVIDENCE")


class ReportBundleValidator:
    def validate(
        self,
        report: ResearchReport,
        markdown: str,
        evidence: ReportEvidenceArtifact,
        manifest: ReportManifest,
    ) -> None:
        validate_report(report)
        _require(evidence == evidence_artifact(report), "EVIDENCE_FILE_MISMATCH")
        _require(
            manifest.model_copy(update={"file_hashes": None}) == build_manifest(report),
            "MANIFEST_MISMATCH",
        )
        _require(markdown == render_markdown(report), "MARKDOWN_MISMATCH")
        evidence_aliases = {entry.display_alias for entry in report.evidence_appendix}
        calculation_aliases = {entry.display_alias for entry in report.calculation_appendix}
        _require(
            set(re.findall(r"\[(E[1-9][0-9]*)\]", markdown)) <= evidence_aliases,
            "UNKNOWN_MARKDOWN_EVIDENCE",
        )
        _require(
            set(re.findall(r"\[(C[1-9][0-9]*)\]", markdown)) <= calculation_aliases,
            "UNKNOWN_MARKDOWN_CALCULATION",
        )

    def validate_directory(self, directory: Path) -> ResearchReport:
        try:
            report_bytes = (directory / "report.json").read_bytes()
            markdown_bytes = (directory / "report.md").read_bytes()
            evidence_bytes = (directory / "evidence.json").read_bytes()
            report = ResearchReport.model_validate_json(report_bytes)
            evidence = ReportEvidenceArtifact.model_validate_json(evidence_bytes)
            manifest = ReportManifest.model_validate_json(
                (directory / "manifest.json").read_bytes()
            )
            markdown = markdown_bytes.decode("utf-8")
        except (OSError, ValidationError, UnicodeError):
            raise ReportIntegrityError("INVALID_BUNDLE_FILES") from None
        self.validate(report, markdown, evidence, manifest)
        hashes = ReportFileHashes.model_validate(
            {
                "report.json": sha256(report_bytes),
                "report.md": sha256(markdown_bytes),
                "evidence.json": sha256(evidence_bytes),
            }
        )
        _require(manifest.file_hashes == hashes, "FILE_HASH_MISMATCH")
        return report
