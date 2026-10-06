"""Evaluation-only, content-addressed authorities from existing deterministic projections.

Relevance selection locates supplied context; it never decides a semantic verdict.
Production claims, financial IDs, prompts and grounding remain unchanged.
"""

import hashlib
import json
from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from financial_research.agent.synthesis_payload import synthesis_projection
from financial_research.schemas.agent import (
    ClaimSection,
    ClaimType,
    EvidenceProjection,
    GroundedResearchAnswer,
    QualityIssueGroup,
)
from financial_research.schemas.base import CanonicalModel, NonEmpty, Ticker
from financial_research.schemas.quality import QualityStatus
from financial_research.schemas.skills import SkillStatus, SynthesisReadiness
from financial_research.schemas.tools import (
    CalculationProvenance,
    EvidenceReference,
)

SUPPORT_PROJECTION_V2 = "stage5-claim-support-projection-v2"
SUPPORT_PROJECTION_VERSION: Literal["stage5-claim-support-projection-v3"] = (
    "stage5-claim-support-projection-v3"
)
SupportVersion = Literal["stage5-claim-support-projection-v2", "stage5-claim-support-projection-v3"]
JUDGE_PROTOCOL_VERSION = "stage5-judge-protocol-v3"


class AuthorityCategory(StrEnum):
    SOURCE_EVIDENCE = "SOURCE_EVIDENCE"
    CALCULATION = "CALCULATION"
    COMPANY_CONTEXT = "COMPANY_CONTEXT"
    QUALITY_DIAGNOSTIC = "QUALITY_DIAGNOSTIC"
    READINESS_STATE = "READINESS_STATE"
    LIMITATION = "LIMITATION"
    AVAILABILITY_STATE = "AVAILABILITY_STATE"
    COMPARISON_STATE = "COMPARISON_STATE"
    MARKET_WINDOW_STATE = "MARKET_WINDOW_STATE"
    STRUCTURAL_STATE = "STRUCTURAL_STATE"


class CompanySupport(CanonicalModel):
    ticker: Ticker
    as_of_date: date
    company_name: str | None = None


class QualitySupport(CanonicalModel):
    status: QualityStatus
    issue_count: Annotated[int, Field(ge=0)] | None = None
    diagnostic: QualityIssueGroup | None = None

    @model_validator(mode="after")
    def summary_or_diagnostic(self) -> "QualitySupport":
        if (self.issue_count is None) == (self.diagnostic is None):
            raise ValueError("quality authority requires a summary count or one diagnostic")
        return self


class ReadinessSupport(CanonicalModel):
    skill_id: NonEmpty
    skill_status: SkillStatus
    synthesis_readiness: SynthesisReadiness


class LimitationSupport(CanonicalModel):
    code: NonEmpty
    section: ClaimSection | None = None
    metric: str | None = None


class FindingSupport(CanonicalModel):
    section: ClaimSection
    metric: NonEmpty
    status: NonEmpty
    direction: str | None = None
    percentage_change_status: str | None = None
    limitations: tuple[str, ...] = ()


class WindowSupport(CanonicalModel):
    lookback_sessions_requested: int
    lookback_sessions_available: int
    status: NonEmpty
    volatility_status: NonEmpty
    annualized: Literal[False]
    limitations: tuple[NonEmpty, ...]


class StructuralSupport(CanonicalModel):
    """A closed set of paths in the supplied synthesis schema, never world absence."""

    field: Literal[
        "market_windows",
        "company_name",
        "findings_by_section",
        "quality.groups",
        "quality.selected_evidence_occurrences",
        "quality.first_affected_date",
        "quality.last_affected_date",
        "limitations",
    ]
    state: Literal["EMPTY", "NONEMPTY", "MISSING", "PRESENT"]
    count: Annotated[int, Field(ge=0)] | None = None
    section: ClaimSection | None = None
    diagnostic_code: NonEmpty | None = None

    @model_validator(mode="after")
    def schema_path_shape(self) -> "StructuralSupport":
        collection = self.field in {
            "market_windows",
            "findings_by_section",
            "quality.groups",
            "quality.selected_evidence_occurrences",
            "limitations",
        }
        if collection:
            if self.count is None or self.state != ("EMPTY" if self.count == 0 else "NONEMPTY"):
                raise ValueError("collection state requires its exact count")
        elif self.count is not None or self.state not in {"MISSING", "PRESENT"}:
            raise ValueError("optional field requires explicit missing/present state")
        if (self.section is not None) != (self.field == "findings_by_section"):
            raise ValueError("section must identify a findings collection")
        grouped = self.field in {
            "quality.selected_evidence_occurrences",
            "quality.first_affected_date",
            "quality.last_affected_date",
        }
        if (self.diagnostic_code is not None) != grouped:
            raise ValueError("diagnostic path must identify its group")
        return self


class SupportAuthority(CanonicalModel):
    category: AuthorityCategory
    evidence: EvidenceReference | None = None
    calculation: CalculationProvenance | None = None
    company: CompanySupport | None = None
    quality: QualitySupport | None = None
    readiness: ReadinessSupport | None = None
    limitation: LimitationSupport | None = None
    finding: FindingSupport | None = None
    window: WindowSupport | None = None
    structural: StructuralSupport | None = None

    @model_validator(mode="after")
    def category_has_exact_payload(self) -> "SupportAuthority":
        expected = {
            AuthorityCategory.SOURCE_EVIDENCE: {"evidence"},
            AuthorityCategory.CALCULATION: {"evidence", "calculation"},
            AuthorityCategory.COMPANY_CONTEXT: {"company"},
            AuthorityCategory.QUALITY_DIAGNOSTIC: {"quality"},
            AuthorityCategory.READINESS_STATE: {"readiness"},
            AuthorityCategory.LIMITATION: {"limitation"},
            AuthorityCategory.AVAILABILITY_STATE: {"finding"},
            AuthorityCategory.COMPARISON_STATE: {"finding"},
            AuthorityCategory.MARKET_WINDOW_STATE: {"window"},
            AuthorityCategory.STRUCTURAL_STATE: {"structural"},
        }[self.category]
        present = {
            key
            for key in type(self).model_fields
            if key != "category" and getattr(self, key) is not None
        }
        if present != expected:
            raise ValueError("support category must have exactly its typed authority payload")
        if self.evidence is not None:
            computed = self.evidence.kind == "COMPUTATION"
            if computed != (self.category == AuthorityCategory.CALCULATION):
                raise ValueError("support evidence kind must match its category")
        if self.calculation is not None and (
            self.evidence is None or self.calculation.evidence_id != self.evidence.evidence_id
        ):
            raise ValueError("calculation and value must share the canonical ID")
        return self


class SupportedClaim(CanonicalModel):
    """Sidecar references; never changes the production GroundedClaim schema."""

    claim_id: NonEmpty
    section: ClaimSection
    claim_type: ClaimType
    statement: Annotated[NonEmpty, Field(max_length=2000)]
    evidence_ids: tuple[NonEmpty, ...] = ()
    support_refs: tuple[NonEmpty, ...] = ()
    dependency_refs: tuple[NonEmpty, ...] = ()


class SupportProjectionError(ValueError):
    pass


def support_id(
    authority: SupportAuthority, version: SupportVersion = SUPPORT_PROJECTION_VERSION
) -> str:
    if authority.evidence is not None:
        return authority.evidence.evidence_id
    prefixes = {
        AuthorityCategory.COMPANY_CONTEXT: "company",
        AuthorityCategory.QUALITY_DIAGNOSTIC: "quality",
        AuthorityCategory.READINESS_STATE: "state",
        AuthorityCategory.LIMITATION: "limitation",
        AuthorityCategory.AVAILABILITY_STATE: "availability",
        AuthorityCategory.COMPARISON_STATE: "comparison",
        AuthorityCategory.MARKET_WINDOW_STATE: "window",
        AuthorityCategory.STRUCTURAL_STATE: "state",
    }
    data = {
        "version": version,
        **authority.model_dump(mode="json", exclude_none=True),
    }
    digest = hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return f"{prefixes[authority.category]}:{digest}"


class ClaimSupportProjection(CanonicalModel):
    support_projection_version: SupportVersion = SUPPORT_PROJECTION_VERSION
    claims: tuple[SupportedClaim, ...]
    support_index: dict[str, SupportAuthority]

    @model_validator(mode="after")
    def references_resolve(self) -> "ClaimSupportProjection":
        if len({c.claim_id for c in self.claims}) != len(self.claims):
            raise ValueError("duplicate support claim IDs")
        for key, authority in self.support_index.items():
            if key != support_id(authority, self.support_projection_version):
                raise ValueError("support ID does not match authoritative content")
        referenced: set[str] = set()
        for claim in self.claims:
            direct = set(claim.support_refs)
            if not set(claim.evidence_ids) <= direct:
                raise ValueError("financial references must be preserved in support refs")
            if self.support_projection_version == SUPPORT_PROJECTION_VERSION:
                financial = {
                    key
                    for key in direct
                    if self.support_index.get(key) is not None
                    and self.support_index[key].evidence is not None
                }
                if financial != set(claim.evidence_ids):
                    raise ValueError("financial support must come only from explicit evidence_ids")
            closure = resolve_dependencies(direct, self.support_index)
            if set(claim.dependency_refs) != closure - direct:
                raise ValueError("claim dependency scope must be exact")
            referenced.update(closure)
        if referenced != set(self.support_index):
            raise ValueError("unrelated support must be excluded")
        return self

    def payload(self) -> str:
        # Resolve again: frozen Pydantic models can still contain mutable dictionaries.
        checked = type(self).model_validate(self.model_dump())
        data = checked.model_dump(mode="json", exclude_none=True)
        for claim in data["claims"]:
            # Native refs already appear in evidence_ids; dependency edges are carried
            # in calculation.input_evidence_ids. Keep exact scopes in the audited model,
            # without repeating potentially hundreds of IDs in every transmitted claim.
            claim["support_refs"] = [
                key for key in claim["support_refs"] if key not in claim["evidence_ids"]
            ]
            claim.pop("dependency_refs")
        for authority in data["support_index"].values():
            for field in ("evidence", "calculation"):
                if field in authority:
                    authority[field].pop("evidence_id", None)
        return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def resolve_dependencies(direct: set[str], index: dict[str, SupportAuthority]) -> set[str]:
    resolved = set(direct)
    pending = list(direct)
    while pending:
        key = pending.pop()
        if key not in index:
            raise SupportProjectionError("UNKNOWN_SUPPORT_REF")
        calculation = index[key].calculation
        if calculation is not None:
            for dependency in calculation.input_evidence_ids:
                if dependency not in resolved:
                    resolved.add(dependency)
                    pending.append(dependency)
    return resolved


def authority_catalog(projection: EvidenceProjection) -> dict[str, SupportAuthority]:
    """Copy existing outputs, without arithmetic, external knowledge or new financial facts."""
    catalog: dict[str, SupportAuthority] = {}

    def add(authority: SupportAuthority) -> None:
        catalog[support_id(authority)] = authority

    calculations = {c.evidence_id: c for c in projection.calculation_provenance}
    for reference in projection.evidence_index.values():
        if reference.kind == "COMPUTATION":
            add(
                SupportAuthority(
                    category=AuthorityCategory.CALCULATION,
                    evidence=reference,
                    calculation=calculations[reference.evidence_id],
                )
            )
        else:
            add(SupportAuthority(category=AuthorityCategory.SOURCE_EVIDENCE, evidence=reference))
    add(
        SupportAuthority(
            category=AuthorityCategory.COMPANY_CONTEXT,
            company=CompanySupport(
                ticker=projection.ticker,
                as_of_date=projection.as_of_date,
                company_name=projection.company_name,
            ),
        )
    )
    add(
        SupportAuthority(
            category=AuthorityCategory.READINESS_STATE,
            readiness=ReadinessSupport(
                skill_id=projection.skill_id,
                skill_status=projection.skill_status,
                synthesis_readiness=projection.synthesis_readiness,
            ),
        )
    )
    quality = synthesis_projection(projection).quality
    add(
        SupportAuthority(
            category=AuthorityCategory.QUALITY_DIAGNOSTIC,
            quality=QualitySupport(status=quality.status, issue_count=quality.issue_count),
        )
    )
    for group in quality.groups:
        add(
            SupportAuthority(
                category=AuthorityCategory.QUALITY_DIAGNOSTIC,
                quality=QualitySupport(status=quality.status, diagnostic=group),
            )
        )
    for finding in projection.findings:
        category = (
            AuthorityCategory.COMPARISON_STATE
            if finding.percentage_change_status is not None
            else AuthorityCategory.AVAILABILITY_STATE
        )
        add(
            SupportAuthority(
                category=category,
                finding=FindingSupport.model_validate(
                    finding.model_dump(exclude={"evidence_ids", "calculation_ids"})
                ),
            )
        )
        for code in finding.limitations:
            add(
                SupportAuthority(
                    category=AuthorityCategory.LIMITATION,
                    limitation=LimitationSupport(
                        code=code, section=finding.section, metric=finding.metric
                    ),
                )
            )
    for code in projection.limitations:
        add(
            SupportAuthority(
                category=AuthorityCategory.LIMITATION, limitation=LimitationSupport(code=code)
            )
        )
    for window in projection.market_windows:
        add(
            SupportAuthority(
                category=AuthorityCategory.MARKET_WINDOW_STATE,
                window=WindowSupport.model_validate(
                    window.model_dump(
                        exclude={
                            "cumulative_return",
                            "realized_volatility_daily",
                            "window_high",
                            "window_low",
                        }
                    )
                ),
            )
        )

    # These fields are always present in SynthesisProjection. Counts describe only
    # this supplied context, not upstream coverage or real-world nonexistence.
    def structure(**fields: object) -> None:
        add(
            SupportAuthority(
                category=AuthorityCategory.STRUCTURAL_STATE,
                structural=StructuralSupport.model_validate(fields),
            )
        )

    for field, count in (
        ("market_windows", len(projection.market_windows)),
        ("quality.groups", len(quality.groups)),
        ("limitations", len(projection.limitations)),
    ):
        structure(field=field, count=count, state="EMPTY" if count == 0 else "NONEMPTY")
    structure(
        field="company_name", state="MISSING" if projection.company_name is None else "PRESENT"
    )
    for section in ClaimSection:
        count = sum(f.section == section for f in projection.findings)
        structure(
            field="findings_by_section",
            section=section,
            count=count,
            state="EMPTY" if count == 0 else "NONEMPTY",
        )
    for group in quality.groups:
        count = len(group.selected_evidence_occurrences)
        structure(
            field="quality.selected_evidence_occurrences",
            diagnostic_code=group.code,
            count=count,
            state="EMPTY" if count == 0 else "NONEMPTY",
        )
        for field in ("first_affected_date", "last_affected_date"):
            structure(
                field=f"quality.{field}",
                diagnostic_code=group.code,
                state="MISSING" if getattr(group, field) is None else "PRESENT",
            )
    return dict(sorted(catalog.items()))


def nonfinancial_scope(
    claim: SupportedClaim, projection: EvidenceProjection, catalog: dict[str, SupportAuthority]
) -> set[str]:
    """Bounded section scopes over the selected Skill's actual typed synthesis fields.

    GroundedClaim has no metric/finding tag. All states in the relevant section are
    therefore supplied, including missing metrics with no financial citation. No
    prose matching or LLM extraction is used. Finding authorities omit values,
    periods and evidence links, so this cannot enlarge financial citation scope.
    """
    if claim.claim_type not in set(ClaimType):
        raise SupportProjectionError("UNSUPPORTED_CLAIM_TYPE")
    sections = {claim.section}
    if claim.section == ClaimSection.QUALITY:
        sections = set(ClaimSection)
    elif claim.section == ClaimSection.FUNDAMENTALS:
        sections.add(ClaimSection.QUALITY)  # exact research-quality missing-metric state
    elif claim.section == ClaimSection.COMPANY and projection.skill_id == "company_overview":
        sections.add(ClaimSection.FUNDAMENTALS)  # supplied snapshot availability
    selected: set[str] = set()
    for key, authority in catalog.items():
        if authority.evidence is not None:
            continue  # Financial facts/calculations enter only through evidence_ids.
        relevant = authority.company is not None or authority.readiness is not None
        if authority.quality is not None:
            relevant = claim.section == ClaimSection.QUALITY
        if authority.finding is not None:
            relevant = authority.finding.section in sections
        if authority.limitation is not None:
            relevant = (
                authority.limitation.section is None or authority.limitation.section in sections
            )
        if authority.window is not None:
            relevant = claim.section in {ClaimSection.MARKET, ClaimSection.QUALITY}
        if authority.structural is not None:
            state = authority.structural
            relevant = (
                claim.section == ClaimSection.QUALITY
                or state.field == "company_name"
                or state.field == "limitations"
                or (state.field == "findings_by_section" and state.section in sections)
                or (state.field == "market_windows" and claim.section == ClaimSection.MARKET)
            )
        if relevant:
            selected.add(key)
    return selected


def project_claim_support(
    claims: tuple[SupportedClaim, ...], projection: EvidenceProjection
) -> ClaimSupportProjection:
    catalog = authority_catalog(projection)
    selected: dict[str, SupportAuthority] = {}
    scoped = []
    for claim in claims:
        direct = set(claim.evidence_ids) | set(claim.support_refs)
        resolve_dependencies(direct, catalog)  # Fail on unknown explicit refs.
        if any(
            catalog[key].evidence is not None and key not in claim.evidence_ids for key in direct
        ):
            raise SupportProjectionError("FINANCIAL_SUPPORT_OUTSIDE_CITATIONS")
        direct.update(nonfinancial_scope(claim, projection, catalog))
        closure = resolve_dependencies(direct, catalog)
        selected.update({key: catalog[key] for key in closure})
        scoped.append(
            claim.model_copy(
                update={
                    "support_refs": tuple(sorted(direct)),
                    "dependency_refs": tuple(sorted(closure - direct)),
                }
            )
        )
    return ClaimSupportProjection(
        claims=tuple(scoped), support_index=dict(sorted(selected.items()))
    )


def support_for_answer(
    answer: GroundedResearchAnswer, projection: EvidenceProjection
) -> ClaimSupportProjection:
    if (
        answer.ticker,
        answer.as_of_date,
        answer.citations,
        answer.calculation_provenance,
        answer.quality,
        answer.synthesis_readiness,
        answer.used_skill_ids,
    ) != (
        projection.ticker,
        projection.as_of_date,
        projection.evidence_index,
        projection.calculation_provenance,
        projection.quality,
        projection.synthesis_readiness,
        (projection.skill_id,),
    ):
        raise SupportProjectionError("AUTHORITATIVE_SUPPORT_MISMATCH")
    return project_claim_support(
        tuple(SupportedClaim.model_validate(c.model_dump()) for c in answer.claims), projection
    )
