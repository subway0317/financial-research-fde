"""Offline structural acceptance replay of archived claims; no Agent/Judge calls."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal

from financial_research.agent.evidence_projection import project_evidence
from financial_research.evals.dataset import DEFAULT_ROOT, load_suite
from financial_research.evals.fixtures import fixture_registry, load_fixtures
from financial_research.evals.schemas import EvaluationReport
from financial_research.evals.support import (
    JUDGE_PROTOCOL_VERSION,
    SUPPORT_PROJECTION_VERSION,
    AuthorityCategory,
    ClaimSupportProjection,
    SupportAuthority,
    authority_catalog,
    resolve_dependencies,
    support_for_answer,
)
from financial_research.schemas.agent import EvidenceProjection
from financial_research.schemas.base import CanonicalModel, NonEmpty

AUDIT_FILE = "replay/stage5-support-v3-audit-v1.json"


class AuthorityRequirement(CanonicalModel):
    category: AuthorityCategory
    metric: str | None = None
    code: str | None = None
    field: str | None = None
    state: str | None = None

    def matches(self, authority: SupportAuthority) -> bool:
        if authority.category != self.category:
            return False
        if self.metric is not None and (
            authority.finding is None or authority.finding.metric != self.metric
        ):
            return False
        if self.code is not None:
            actual = (
                authority.quality.diagnostic.code
                if authority.quality and authority.quality.diagnostic
                else authority.limitation.code
                if authority.limitation
                else None
            )
            if actual != self.code:
                return False
        if self.field is not None and (
            authority.structural is None or authority.structural.field != self.field
        ):
            return False
        if self.state is not None:
            actual = (
                authority.structural.state
                if authority.structural
                else authority.finding.status
                if authority.finding
                else None
            )
            if actual != self.state:
                return False
        return True


class AuditTarget(CanonicalModel):
    audit_number: int
    case_id: NonEmpty
    claim_id: NonEmpty
    kind: Literal["BINDING", "ABSENCE", "FINANCIAL_CITATION"]
    old_support_issue: NonEmpty
    required_authorities: tuple[AuthorityRequirement, ...] = ()
    omitted_financial_ids: tuple[NonEmpty, ...] = ()


class ReplayLedger(CanonicalModel):
    audit_version: Literal["stage5-support-v3-audit-v1"]
    targets: tuple[AuditTarget, ...]


def load_replay_ledger() -> ReplayLedger:
    return ReplayLedger.model_validate_json((DEFAULT_ROOT / AUDIT_FILE).read_text())


def requirement_refs(
    requirement: AuthorityRequirement, support: ClaimSupportProjection, claim_id: str
) -> tuple[str, ...]:
    claim = next(c for c in support.claims if c.claim_id == claim_id)
    return tuple(
        key for key in claim.support_refs if requirement.matches(support.support_index[key])
    )


def replay_support(source: EvaluationReport) -> dict[str, object]:
    """Rebuild scope from frozen fixtures while preserving every original claim/citation.

    The audit ledger is an acceptance oracle, never consulted by scope selection.
    It records identified defects, not expected new semantic verdicts.
    """
    suite, _ = load_suite()
    cases = {c.case_id: c for c in suite.cases}
    fixtures = load_fixtures(DEFAULT_ROOT)
    projections: dict[tuple[str, str], EvidenceProjection] = {}
    rebuilt: dict[str, ClaimSupportProjection] = {}
    financial_checks: dict[tuple[str, str], bool] = {}
    closure_checks: dict[tuple[str, str], bool] = {}
    original = {c.case_id: c for c in source.cases}
    for row in source.cases:
        if row.answer is None or not row.answer.claims:
            continue
        key = (cases[row.case_id].fixture_scenario, row.answer.used_skill_ids[0])
        if key not in projections:
            fixture = fixtures[key[0]]
            result = (
                fixture_registry(fixture)
                .get(key[1])
                .run(ticker=fixture.context.ticker, as_of_date=fixture.context.as_of_date)
            )
            projections[key] = project_evidence(result)
        projection = projections[key]
        support = support_for_answer(row.answer, projection)
        rebuilt[row.case_id] = support
        catalog = authority_catalog(projection)
        for claim, supplied in zip(support.claims, row.answer.claims, strict=True):
            identity = (row.case_id, claim.claim_id)
            direct = set(claim.support_refs)
            closure = resolve_dependencies(direct, support.support_index)
            financial = {k for k in closure if support.support_index[k].evidence is not None}
            expected = resolve_dependencies(set(supplied.evidence_ids), catalog)
            financial_checks[identity] = (
                claim.evidence_ids == supplied.evidence_ids and financial == expected
            )
            closure_checks[identity] = closure - direct == set(claim.dependency_refs)
    results = []
    resolved = {"BINDING": 0, "ABSENCE": 0, "FINANCIAL_CITATION": 0}
    ledger = load_replay_ledger()
    expected_counts = {"BINDING": 10, "ABSENCE": 5, "FINANCIAL_CITATION": 5}
    if (
        len({(t.case_id, t.claim_id) for t in ledger.targets}) != 20
        or {kind: sum(t.kind == kind for t in ledger.targets) for kind in resolved}
        != expected_counts
    ):
        raise ValueError("replay audit ledger is incomplete")
    for target in ledger.targets:
        row = original[target.case_id]
        if row.claim_support_projection is None:
            raise ValueError("replay requires the original v2 claim scope")
        if not any(
            e.claim_id == target.claim_id and e.verdict == "INSUFFICIENT"
            for e in row.claim_evaluations
        ):
            raise ValueError("audit target is not an archived insufficient claim")
        support = rebuilt[target.case_id]
        claim = next(c for c in support.claims if c.claim_id == target.claim_id)
        requirements = [
            {
                "requirement": r.model_dump(mode="json", exclude_none=True),
                "old_refs": requirement_refs(r, row.claim_support_projection, target.claim_id),
                "v3_refs": requirement_refs(r, support, target.claim_id),
            }
            for r in target.required_authorities
        ]
        scope = set(claim.support_refs + claim.dependency_refs)
        omissions_preserved = (
            bool(target.omitted_financial_ids)
            and all(
                k in row.answer.citations and k not in scope for k in target.omitted_financial_ids
            )
            if row.answer
            else False
        )
        identity = (target.case_id, target.claim_id)
        passed = (
            financial_checks[identity]
            and closure_checks[identity]
            and (
                omissions_preserved
                if target.kind == "FINANCIAL_CITATION"
                else bool(requirements)
                and all(r["v3_refs"] for r in requirements)
                and any(not r["old_refs"] for r in requirements)
            )
        )
        resolved[target.kind] += int(passed)
        results.append(
            {
                **target.model_dump(mode="json"),
                "authority_resolution": requirements,
                "dependency_closure_complete": closure_checks[identity],
                "financial_scope_unchanged": financial_checks[identity],
                "omissions_not_autofilled": omissions_preserved
                if target.kind == "FINANCIAL_CITATION"
                else None,
                "passed": passed,
            }
        )
    return {
        "source_run_id": source.run_id,
        "support_projection_version": SUPPORT_PROJECTION_VERSION,
        "judge_protocol_version": JUDGE_PROTOCOL_VERSION,
        "claim_count": len(financial_checks),
        "binding_resolved": resolved["BINDING"],
        "absence_resolved": resolved["ABSENCE"],
        "citation_omissions_not_autofilled": resolved["FINANCIAL_CITATION"],
        "all_financial_scopes_unchanged": all(financial_checks.values()),
        "all_dependency_closures_complete": all(closure_checks.values()),
        "acceptable": resolved == expected_counts
        and all(financial_checks.values())
        and all(closure_checks.values()),
        "semantic_verdicts_changed": False,
        "llm_calls": 0,
        "targets": results,
        "projections": {k: v.model_dump(mode="json") for k, v in rebuilt.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    raw = args.source_report.read_bytes()
    result = replay_support(EvaluationReport.model_validate_json(raw))
    projections = result.pop("projections")
    result["source_report_sha256"] = hashlib.sha256(raw).hexdigest()
    result["audit_ledger_sha256"] = hashlib.sha256(
        (DEFAULT_ROOT / AUDIT_FILE).read_bytes()
    ).hexdigest()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for name, data in (
        ("support_replay.json", result),
        ("claim_support_projections.json", projections),
    ):
        with (args.output_dir / name).open("x") as handle:
            handle.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "targets"}, indent=2))
    raise SystemExit(0 if result["acceptable"] else 1)


if __name__ == "__main__":
    main()
