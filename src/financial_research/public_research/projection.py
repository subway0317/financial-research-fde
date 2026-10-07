"""Project validated internal research at the HTTP boundary, without recalculation."""

import hashlib
import json
from collections import defaultdict
from datetime import date

from financial_research.agent.rendering import render_answer
from financial_research.public_research.policy import is_market_source
from financial_research.public_research.schemas import (
    PublicCalculationAppendixEntry,
    PublicCalculationProvenance,
    PublicCompanySnapshotResult,
    PublicEquityResearchReportResponse,
    PublicEvidenceAppendixEntry,
    PublicEvidenceReference,
    PublicFundamentalTrendResult,
    PublicGroundedResearchAnswer,
    PublicInputSummary,
    PublicMarketBehaviorResult,
    PublicMetricTrendResult,
    PublicPeriodComparisonResult,
    PublicReportManifest,
    PublicResearchQualityResult,
    PublicResearchReport,
    PublicToolResult,
)
from financial_research.reports.schemas import EquityResearchReportResponse, ReportSection
from financial_research.schemas.agent import GroundedClaim, GroundedResearchAnswer
from financial_research.schemas.tools import (
    CalculationProvenance,
    CompanySnapshotResult,
    EvidenceReference,
    FundamentalTrendResult,
    MarketBehaviorResult,
    MetricTrendResult,
    PeriodComparisonResult,
    ResearchQualityResult,
    ToolResult,
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _input_digest(refs: tuple[EvidenceReference, ...]) -> str:
    return _digest([ref.model_dump(mode="json") for ref in refs])


def _range(refs: tuple[EvidenceReference, ...]) -> tuple[date | None, date | None]:
    dates = [
        value
        for ref in refs
        for value in (ref.date, ref.period_start, ref.period_end)
        if value is not None
    ]
    return (min(dates), max(dates)) if dates else (None, None)


def project_references(
    references: tuple[EvidenceReference, ...],
) -> tuple[tuple[PublicEvidenceReference, ...], dict[str, str]]:
    groups: dict[str, list[EvidenceReference]] = defaultdict(list)
    public: dict[str, PublicEvidenceReference] = {}
    mapping: dict[str, str] = {}
    for ref in references:
        if not is_market_source(ref):
            public[ref.evidence_id] = PublicEvidenceReference(
                **ref.model_dump(), disclosure="FULL_FACT"
            )
            mapping[ref.evidence_id] = ref.evidence_id
            continue
        # Group by window/field/provenance, never by session or source value.
        metadata = {
            "metric": ref.metric,
            "provider": ref.provider,
            "source_reference": ref.source_reference.partition("#")[0],
            "unit": ref.unit,
            "data_vintage": ref.data_vintage,
            "transformation": ref.transformation,
        }
        key = "public-market-summary:" + _digest(metadata)
        groups[key].append(ref)
    for key, rows in groups.items():
        refs = tuple(sorted(rows, key=lambda row: row.evidence_id))
        ref = refs[0]
        start, end = _range(refs)
        digest = _input_digest(refs)
        summary_id = "public-market-summary:" + _digest((key, digest))
        mapping.update((row.evidence_id, summary_id) for row in refs)
        public[summary_id] = PublicEvidenceReference(
            evidence_id=summary_id,
            kind=ref.kind,
            metric=ref.metric,
            provider=ref.provider,
            source_reference=ref.source_reference.partition("#")[0],
            unit=ref.unit,
            data_vintage=ref.data_vintage,
            transformation=ref.transformation,
            disclosure="MARKET_INPUT_SUMMARY",
            observation_count=len(refs),
            input_range_start=start,
            input_range_end=end,
            internal_input_digest=digest,
        )
    return tuple(public[key] for key in sorted(public)), mapping


def project_calculations(
    calculations: tuple[CalculationProvenance, ...], references: tuple[EvidenceReference, ...]
) -> tuple[PublicCalculationProvenance, ...]:
    index = {ref.evidence_id: ref for ref in references}
    public = []
    for calc in calculations:
        refs = tuple(index[key] for key in calc.input_evidence_ids)
        result = index[calc.evidence_id]
        start, end = _range(refs)
        withheld = sum(is_market_source(ref) for ref in refs)
        public.append(
            PublicCalculationProvenance(
                **calc.model_dump(exclude={"input_evidence_ids"}),
                input_evidence_ids=tuple(
                    ref.evidence_id for ref in refs if not is_market_source(ref)
                ),
                metric=result.metric,
                result=result.value,
                unit=result.unit,
                methodology=(
                    "Deterministic calculation over internal session observations; "
                    "full market inputs are retained in the internal audit."
                    if withheld
                    else "Deterministic calculation over the cited non-market or derived facts."
                ),
                input_summary=PublicInputSummary(
                    input_count=len(refs),
                    withheld_market_input_count=withheld,
                    input_range_start=start,
                    input_range_end=end,
                    input_kind=(
                        "SESSION_MARKET_OBSERVATIONS" if withheld else "NON_MARKET_OR_DERIVED_FACTS"
                    ),
                    input_metrics=tuple(sorted({ref.metric for ref in refs})),
                    internal_input_digest=_input_digest(refs),
                ),
            )
        )
    return tuple(public)


def _claims(
    claims: tuple[GroundedClaim, ...], mapping: dict[str, str]
) -> tuple[GroundedClaim, ...]:
    return tuple(
        GroundedClaim.model_validate(
            {
                **claim.model_dump(),
                "evidence_ids": tuple(dict.fromkeys(mapping[key] for key in claim.evidence_ids)),
            }
        )
        for claim in claims
    )


def project_report(response: EquityResearchReportResponse) -> PublicEquityResearchReportResponse:
    from financial_research.public_research.rendering import render_public_markdown

    internal = response.report
    refs = tuple(entry.evidence for entry in internal.evidence_appendix)
    evidence, mapping = project_references(refs)
    aliases = {ref.evidence_id: f"E{index}" for index, ref in enumerate(evidence, 1)}
    calculations = project_calculations(
        tuple(entry.provenance for entry in internal.calculation_appendix), refs
    )
    projected_calcs = {calc.evidence_id: calc for calc in calculations}
    report = PublicResearchReport.model_validate(
        {
            **internal.model_dump(),
            "sections": tuple(
                ReportSection(
                    section_id=section.section_id, claims=_claims(section.claims, mapping)
                )
                for section in internal.sections
            ),
            "evidence_appendix": tuple(
                PublicEvidenceAppendixEntry(
                    display_alias=aliases[ref.evidence_id],
                    canonical_id=ref.evidence_id,
                    evidence=ref,
                )
                for ref in evidence
            ),
            "calculation_appendix": tuple(
                PublicCalculationAppendixEntry.model_validate(
                    {
                        **entry.model_dump(),
                        "provenance": projected_calcs[entry.canonical_id],
                        "input_display_aliases": tuple(
                            aliases[key]
                            for key in projected_calcs[entry.canonical_id].input_evidence_ids
                        ),
                    }
                )
                for entry in internal.calculation_appendix
            ),
        }
    )
    manifest = PublicReportManifest.model_validate(
        {
            **response.manifest_summary.model_dump(),
            "evidence_count": len(evidence),
            "calculation_count": len(calculations),
            "file_hashes": None,
        }
    )
    return PublicEquityResearchReportResponse(
        report=report, markdown=render_public_markdown(report), manifest_summary=manifest
    )


def project_agent(answer: GroundedResearchAnswer) -> PublicGroundedResearchAnswer:
    refs = tuple(answer.citations.values())
    evidence, mapping = project_references(refs)
    claims = _claims(answer.claims, mapping)
    # The existing narrative renderer reads claims/metadata only. Internal grounding
    # has already completed; only citation presentation changes here.
    rendered = render_answer(answer.model_copy(update={"claims": claims}))
    return PublicGroundedResearchAnswer.model_validate(
        {
            **answer.model_dump(),
            "claims": claims,
            "citations": {ref.evidence_id: ref for ref in evidence},
            "calculation_provenance": project_calculations(answer.calculation_provenance, refs),
            "rendered_answer": rendered,
        }
    )


def _project_trend(result: MetricTrendResult) -> PublicMetricTrendResult:
    evidence, _ = project_references(result.evidence)
    return PublicMetricTrendResult.model_validate(
        {
            **result.model_dump(),
            "evidence": evidence,
            "calculation_provenance": project_calculations(
                result.calculation_provenance, result.evidence
            ),
        }
    )


def project_tool_result(result: ToolResult) -> PublicToolResult:
    models: dict[type[ToolResult], type[PublicToolResult]] = {
        CompanySnapshotResult: PublicCompanySnapshotResult,
        FundamentalTrendResult: PublicFundamentalTrendResult,
        PeriodComparisonResult: PublicPeriodComparisonResult,
        MarketBehaviorResult: PublicMarketBehaviorResult,
        ResearchQualityResult: PublicResearchQualityResult,
    }
    # New tool types must explicitly adopt the public contract before exposure.
    model = models[type(result)]
    evidence, _ = project_references(result.evidence)
    data = result.model_dump()
    data.update(
        evidence=evidence,
        calculation_provenance=project_calculations(result.calculation_provenance, result.evidence),
    )
    if isinstance(result, FundamentalTrendResult):
        data["metrics"] = tuple(_project_trend(row) for row in result.metrics)
    elif isinstance(result, PeriodComparisonResult):
        data["result"] = _project_trend(result.result)
    return model.model_validate(data)
