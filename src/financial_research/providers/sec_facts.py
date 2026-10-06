"""SEC-specific companyfacts normalization. No PIT selection or downloads here."""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import ValidationError

from financial_research.exceptions import DataValidationError
from financial_research.fundamentals.registry import METRIC_REGISTRY, PeriodType
from financial_research.providers.http import JsonResponse
from financial_research.providers.sec_concepts import SEC_CONCEPTS
from financial_research.schemas.base import canonical_cik
from financial_research.schemas.company import CompanyProfile
from financial_research.schemas.fundamentals import FundamentalSourceDataset, SourceFundamentalFact
from financial_research.schemas.quality import QualityIssue, Severity

logger = logging.getLogger(__name__)
SUPPORTED_FORMS = frozenset({"10-Q", "10-K", "10-Q/A", "10-K/A"})


@dataclass(frozen=True)
class Candidate:
    priority: int
    concept: str
    fact: SourceFundamentalFact


def normalize_companyfacts(
    company: CompanyProfile, response: JsonResponse
) -> FundamentalSourceDataset:
    try:
        if canonical_cik(response.payload["cik"]) != company.cik:
            raise ValueError("companyfacts CIK mismatch")
        all_facts = response.payload["facts"]
        if not isinstance(all_facts, dict):
            raise ValueError("facts must be an object")
        taxonomy = all_facts.get("us-gaap", {})
        if not isinstance(taxonomy, dict):
            raise ValueError("invalid us-gaap taxonomy")
        facts = []
        issues = []
        for metric, definition in METRIC_REGISTRY.items():
            candidates: dict[tuple[date | None, date, str], list[Candidate]] = {}
            for priority, concept in enumerate(SEC_CONCEPTS[metric]):
                if concept not in taxonomy:
                    continue
                units = taxonomy[concept]["units"]
                if not isinstance(units, dict):
                    raise ValueError("invalid units object")
                if definition.unit not in units:
                    issues.append(
                        QualityIssue(
                            code="UNSUPPORTED_UNIT",
                            severity=Severity.WARNING,
                            message=f"{metric}: source lacks {definition.unit} observations",
                            affected_field=metric,
                        )
                    )
                    continue
                rows = units[definition.unit]
                if not isinstance(rows, list):
                    raise ValueError("concept observations must be a list")
                for row in rows:
                    if not isinstance(row, dict):
                        raise ValueError("concept observation must be an object")
                    form = row["form"]
                    if form not in SUPPORTED_FORMS:
                        issues.append(
                            QualityIssue(
                                code="UNSUPPORTED_FORM",
                                severity=Severity.INFO,
                                message=f"{metric}: form {form} outside registered US-GAAP scope",
                                affected_field=metric,
                                affected_context=str(row.get("accn")),
                            )
                        )
                        continue
                    fact = _normalize_row(company, response, metric, concept, row)
                    if (definition.period_type == PeriodType.DURATION) != (
                        fact.period_start is not None
                    ):
                        raise ValueError(f"{metric}: invalid duration/instant semantics")
                    key = (fact.period_start, fact.period_end, fact.accession_number)
                    candidates.setdefault(key, []).append(Candidate(priority, concept, fact))
            for key in sorted(candidates, key=lambda item: (item[0] or date.min, item[1], item[2])):
                group = sorted(candidates[key], key=lambda item: item.priority)
                chosen = group[0]
                seen_aliases = {chosen.priority: chosen}
                for candidate in group[1:]:
                    if candidate.fact.filed_at != chosen.fact.filed_at:
                        raise ValueError("inconsistent filing dates for one accession/period")
                    previous = seen_aliases.get(candidate.priority)
                    if previous is not None and candidate.fact.value != previous.fact.value:
                        raise ValueError("conflicting duplicates of the same SEC concept")
                    seen_aliases[candidate.priority] = candidate
                    conflicting = candidate.fact.value != chosen.fact.value
                    issues.append(
                        QualityIssue(
                            code="ALIAS_VALUE_CONFLICT" if conflicting else "DUPLICATE_SOURCE_FACT",
                            severity=Severity.WARNING if conflicting else Severity.INFO,
                            message=(
                                f"{metric}: selected registered alias priority {chosen.priority}; "
                                f"redundant priority {candidate.priority} recorded"
                            ),
                            affected_field=metric,
                            affected_date=chosen.fact.period_end,
                            affected_context=chosen.fact.accession_number,
                        )
                    )
                facts.append(chosen.fact)
        facts.sort(
            key=lambda fact: (
                fact.metric,
                fact.period_end,
                fact.period_start or date.min,
                fact.filed_at,
                fact.accession_number,
            )
        )
        logger.info("SEC fundamentals normalized ticker=%s facts=%d", company.ticker, len(facts))
        return FundamentalSourceDataset(
            facts=tuple(facts), provenance=response.provenance, issues=tuple(issues)
        )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise DataValidationError("SEC companyfacts failed canonical normalization") from exc


def _normalize_row(
    company: CompanyProfile, response: JsonResponse, metric: str, concept: str, row: dict[str, Any]
) -> SourceFundamentalFact:
    provenance = response.provenance
    return SourceFundamentalFact.model_validate(
        {
            "ticker": company.ticker,
            "metric": metric,
            "value": row["val"],
            "unit": "USD",
            "period_start": row.get("start"),
            "period_end": row["end"],
            "filed_at": row["filed"],
            "form": row["form"],
            "accession_number": row["accn"],
            "provider": provenance.provider,
            "source_reference": (
                f"{provenance.source_reference}#us-gaap/{concept}/USD/{row['accn']}"
            ),
            "retrieved_at": provenance.retrieved_at,
            "data_vintage": provenance.data_vintage,
            "transformation": (
                f"us-gaap:{concept} -> canonical:{metric}; ordered aliases per filing",
            ),
        }
    )
