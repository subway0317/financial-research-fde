"""Compact projection serialization and safe byte accounting; no financial calculations."""

import json
import logging
from collections import Counter, defaultdict
from datetime import date

from financial_research.agent.prompts import SYNTHESIS_PROMPT
from financial_research.schemas.agent import (
    EvidenceProjection,
    QualityIssueGroup,
    QualityOccurrence,
    ResponseLanguage,
    SynthesisCalculation,
    SynthesisEvidenceDefinition,
    SynthesisEvidenceProvenance,
    SynthesisFinding,
    SynthesisOutput,
    SynthesisPayloadAudit,
    SynthesisPayloadComponents,
    SynthesisProjection,
    SynthesisQualitySummary,
)
from financial_research.schemas.quality import QualityIssue, Severity

logger = logging.getLogger(__name__)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _bytes(value: object) -> int:
    return len(_json(value).encode("utf-8"))


def _selected_occurrence(issue: QualityIssue, projection: EvidenceProjection) -> bool:
    """Match recorded metric and source context/date; never infer PIT availability."""
    for reference in projection.evidence_index.values():
        if issue.affected_field is not None and issue.affected_field != reference.metric:
            continue
        if issue.affected_context:
            if issue.affected_context in reference.source_reference:
                return True
        elif issue.affected_date is not None and issue.affected_date in {
            reference.date,
            reference.period_start,
            reference.period_end,
            reference.filed_at,
            reference.available_date,
        }:
            return True
    return False


def _quality_summary(projection: EvidenceProjection) -> SynthesisQualitySummary:
    grouped: dict[tuple[Severity, str, str, str | None], list[QualityIssue]] = defaultdict(list)
    for issue in projection.quality.issues:
        key = (issue.severity, issue.code, issue.message, issue.affected_field)
        grouped[key].append(issue)
    groups = []
    for key in sorted(grouped, key=lambda key: (*key[:3], key[3] is not None, key[3] or "")):
        issues = grouped[key]
        template = issues[0]
        dates = [issue.affected_date for issue in issues if issue.affected_date is not None]
        selected: Counter[tuple[date | None, str | None]] = Counter(
            (issue.affected_date, issue.affected_context)
            for issue in issues
            if _selected_occurrence(issue, projection)
        )
        occurrences = tuple(
            QualityOccurrence(affected_date=session, affected_context=context, count=count)
            for (session, context), count in sorted(
                selected.items(),
                key=lambda item: (
                    item[0][0] is not None,
                    item[0][0] or date.min,
                    item[0][1] is not None,
                    item[0][1] or "",
                ),
            )
        )
        groups.append(
            QualityIssueGroup(
                code=template.code,
                severity=template.severity,
                message=template.message,
                affected_field=template.affected_field,
                count=len(issues),
                first_affected_date=min(dates) if dates else None,
                last_affected_date=max(dates) if dates else None,
                selected_evidence_occurrences=occurrences,
            )
        )
    return SynthesisQualitySummary(
        status=projection.quality.status,
        issue_count=len(projection.quality.issues),
        groups=tuple(groups),
    )


def synthesis_projection(projection: EvidenceProjection) -> SynthesisProjection:
    """Keep every canonical evidence ID and input chain; group repetitive diagnostics."""
    evidence_index = {}
    provenance_index = {}
    for key, ref in sorted(projection.evidence_index.items()):
        provenance = SynthesisEvidenceProvenance(
            provider=ref.provider,
            data_vintage=ref.data_vintage,
            transformation=ref.transformation,
        )
        provenance_id = provenance.stable_id()
        provenance_index[provenance_id] = provenance
        evidence_index[key] = SynthesisEvidenceDefinition.model_validate(
            {**ref.model_dump(), "provenance_id": provenance_id}
        )
    return SynthesisProjection(
        ticker=projection.ticker,
        as_of_date=projection.as_of_date,
        skill_id=projection.skill_id,
        skill_status=projection.skill_status,
        synthesis_readiness=projection.synthesis_readiness,
        quality=_quality_summary(projection),
        company_name=projection.company_name,
        market_windows=tuple(
            sorted(projection.market_windows, key=lambda window: window.lookback_sessions_requested)
        ),
        findings=tuple(
            SynthesisFinding.model_validate(row.model_dump())
            for row in sorted(
                projection.findings, key=lambda row: (row.section, row.metric, row.evidence_ids)
            )
        ),
        evidence_index=evidence_index,
        provenance_index=dict(sorted(provenance_index.items())),
        calculation_provenance={
            calc.evidence_id: SynthesisCalculation.model_validate(calc.model_dump())
            for calc in sorted(projection.calculation_provenance, key=lambda calc: calc.evidence_id)
        },
        limitations=tuple(sorted(set(projection.limitations))),
    )


def synthesis_payload(
    *,
    question: str,
    projection: EvidenceProjection,
    response_language: ResponseLanguage | None = None,
) -> tuple[str, SynthesisPayloadAudit]:
    compact = synthesis_projection(projection)
    data = compact.model_dump(mode="json", exclude_none=True)
    language_metadata = (
        {"response_language": response_language} if response_language is not None else {}
    )
    payload = _json({"question": question, **language_metadata, "projection": data})
    baseline_data = projection.model_dump(mode="json")
    baseline = {"question": question, **language_metadata, "projection": baseline_data}
    metadata = {
        key: value
        for key, value in data.items()
        if key
        not in {
            "findings",
            "evidence_index",
            "provenance_index",
            "calculation_provenance",
            "quality",
            "limitations",
        }
    }
    audit = SynthesisPayloadAudit(
        baseline_request_bytes=_bytes(baseline),
        request_bytes=len(payload.encode("utf-8")),
        baseline_quality_bytes=_bytes(baseline_data["quality"]),
        instruction_bytes=len(SYNTHESIS_PROMPT.encode("utf-8")),
        # Pydantic schema before the SDK's small strict-format wrapper; no tokenizer estimate.
        output_schema_bytes=_bytes(SynthesisOutput.model_json_schema()),
        components=SynthesisPayloadComponents(
            request_metadata_bytes=_bytes({"question": question, **language_metadata, **metadata}),
            findings_bytes=_bytes(data["findings"]),
            # Include both evidence definitions and their shared provenance without
            # changing the public numeric-only audit contract.
            evidence_definitions_bytes=_bytes(
                {
                    "evidence_index": data["evidence_index"],
                    "provenance_index": data["provenance_index"],
                }
            ),
            calculation_provenance_bytes=_bytes(data["calculation_provenance"]),
            quality_bytes=_bytes(data["quality"]),
            limitations_bytes=_bytes(data["limitations"]),
        ),
        evidence_count=len(compact.evidence_index),
        calculation_count=len(compact.calculation_provenance),
        quality_issue_count=compact.quality.issue_count,
        quality_group_count=len(compact.quality.groups),
    )
    logger.info("synthesis payload audit %s", audit.model_dump_json())
    return payload, audit
