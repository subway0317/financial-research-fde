"""Select canonical findings and their complete calculation-input closure; never calculate."""

from pydantic import ValidationError

from financial_research.agent.errors import AgentIntegrityError
from financial_research.schemas.agent import ClaimSection, EvidenceProjection, ProjectedFinding
from financial_research.schemas.skills import (
    CompanyOverviewResult,
    FundamentalAnalysisResult,
    MarketAnalysisResult,
    ResearchEvidencePackage,
    ResearchQualityAuditResult,
    SkillResult,
)
from financial_research.schemas.tools import EvidenceKind, MarketWindowSummary
from financial_research.skills.readiness import synthesis_readiness


def project_evidence(result: SkillResult) -> EvidenceProjection:
    quality = result.metadata.quality
    if quality is None:
        raise AgentIntegrityError("MISSING_AUTHORITATIVE_QUALITY")
    findings: list[ProjectedFinding] = []
    company_name: str | None = None
    windows: tuple[MarketWindowSummary, ...] = ()
    fundamental = (
        result.fundamental_analysis
        if isinstance(result, (FundamentalAnalysisResult, ResearchEvidencePackage))
        else None
    )
    market = (
        result.market_analysis
        if isinstance(result, (MarketAnalysisResult, ResearchEvidencePackage))
        else None
    )
    company = (
        result.company_overview
        if isinstance(result, (CompanyOverviewResult, ResearchEvidencePackage))
        else None
    )
    audit = (
        result.research_quality
        if isinstance(result, (ResearchQualityAuditResult, ResearchEvidencePackage))
        else None
    )
    for section in (fundamental, market, company, audit):
        if section is not None and not set(section.evidence_ids) <= result.evidence_index.keys():
            raise AgentIntegrityError("UNKNOWN_SKILL_EVIDENCE")
    if fundamental is not None:
        for row in sorted(fundamental.metrics, key=lambda item: item.metric):
            findings.append(
                ProjectedFinding(
                    section=ClaimSection.FUNDAMENTALS,
                    metric=row.metric,
                    status=row.comparison_status,
                    direction=row.direction,
                    percentage_change_status=row.percentage_change_status,
                    evidence_ids=tuple(sorted(row.evidence_ids)),
                    calculation_ids=tuple(sorted(row.calculation_ids)),
                    limitations=tuple(sorted(set(row.limitations))),
                )
            )
    if company is not None:
        company_name = company.company.company_name
        if fundamental is None:
            for snapshot in sorted(company.fundamentals, key=lambda item: item.metric):
                ids = tuple(
                    sorted(
                        key
                        for key in company.evidence_ids
                        if result.evidence_index[key].metric == snapshot.metric
                    )
                )
                findings.append(
                    ProjectedFinding(
                        section=ClaimSection.FUNDAMENTALS,
                        metric=snapshot.metric,
                        status=snapshot.status,
                        evidence_ids=ids,
                        limitations=tuple(sorted(set(snapshot.limitations))),
                    )
                )
    if market is not None or company is not None:
        section_ids = (
            market.evidence_ids if market is not None else company.evidence_ids if company else ()
        )
        latest = (
            market.latest_market_session
            if market is not None
            else company.latest_market_session
            if company
            else None
        )
        chosen = tuple(
            sorted(
                key
                for key in section_ids
                if result.evidence_index[key].kind == EvidenceKind.COMPUTATION
                or (
                    result.evidence_index[key].metric == "close"
                    and result.evidence_index[key].date == latest
                )
            )
        )
        windows = (
            (market.window,) if market is not None else company.market_windows if company else ()
        )
        findings.append(
            ProjectedFinding(
                section=ClaimSection.MARKET,
                metric="observed_market_behavior",
                status=result.metadata.status,
                evidence_ids=chosen,
                calculation_ids=tuple(
                    key
                    for key in chosen
                    if result.evidence_index[key].kind == EvidenceKind.COMPUTATION
                ),
            )
        )
    if audit is not None:
        findings.append(
            ProjectedFinding(
                section=ClaimSection.QUALITY,
                metric="research_quality",
                status=audit.overall_status,
                evidence_ids=tuple(sorted(audit.evidence_ids)),
                calculation_ids=tuple(
                    sorted(
                        key
                        for key in audit.evidence_ids
                        if result.evidence_index[key].kind == EvidenceKind.COMPUTATION
                    )
                ),
                limitations=tuple(
                    f"MISSING_METRIC:{metric}"
                    for metric in sorted(audit.missing_registered_metrics)
                ),
            )
        )
    referenced = {key for finding in findings for key in finding.evidence_ids}
    calculations = {calc.evidence_id: calc for calc in result.calculation_provenance}
    pending = list(referenced)
    while pending:
        key = pending.pop()
        if key not in result.evidence_index:
            raise AgentIntegrityError("UNKNOWN_SKILL_EVIDENCE")
        if result.evidence_index[key].kind == EvidenceKind.COMPUTATION:
            if key not in calculations:
                raise AgentIntegrityError("MISSING_CALCULATION_PROVENANCE")
            for input_id in calculations[key].input_evidence_ids:
                if input_id not in referenced:
                    referenced.add(input_id)
                    pending.append(input_id)
    try:
        return EvidenceProjection(
            ticker=result.metadata.ticker,
            as_of_date=result.metadata.as_of_date,
            skill_id=result.metadata.skill_id,
            skill_status=result.metadata.status,
            synthesis_readiness=synthesis_readiness(result),
            quality=quality,
            company_name=company_name,
            market_windows=tuple(
                sorted(windows, key=lambda item: item.lookback_sessions_requested)
            ),
            findings=tuple(findings),
            evidence_index={key: result.evidence_index[key] for key in sorted(referenced)},
            calculation_provenance=tuple(
                calculations[key] for key in sorted(referenced) if key in calculations
            ),
            limitations=tuple(sorted(set(result.limitations))),
        )
    except ValidationError:
        raise AgentIntegrityError("INVALID_EVIDENCE_PROJECTION") from None
