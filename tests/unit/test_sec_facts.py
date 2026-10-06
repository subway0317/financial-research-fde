import copy
from datetime import UTC, date, datetime

import httpx
import pytest

from financial_research.exceptions import DataValidationError
from financial_research.fundamentals.registry import METRIC_REGISTRY
from financial_research.providers.sec import SECProvider
from financial_research.schemas.company import CompanyProfile
from financial_research.schemas.provenance import ProvenanceRecord, SourceType


def company() -> CompanyProfile:
    return CompanyProfile(
        ticker="ABC",
        company_name="ABC Corp",
        cik="123",
        exchange="Nasdaq",
        currency="USD",
        provenance=ProvenanceRecord(
            provider="fixture",
            source_type=SourceType.SOURCE_FACT,
            source_reference="fixture://company",
            retrieved_at=datetime(2025, 6, 1, tzinfo=UTC),
            data_vintage="v1",
        ),
    )


def row(value: int = 100) -> dict:
    return {
        "start": "2025-01-01",
        "end": "2025-03-31",
        "filed": "2025-05-22",
        "val": value,
        "form": "10-Q",
        "accn": "synthetic-001",
    }


def facts_payload() -> dict:
    return {
        "cik": 123,
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [row()]}},
                "Revenues": {"units": {"USD": [row(90)]}},
            }
        },
    }


def fetch(payload: dict):
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        return SECProvider(
            user_agent="Fixture fixture@example.com", client=client
        ).get_fundamentals(company())


def test_ordered_alias_resolution_has_conflict_record() -> None:
    result = fetch(facts_payload())
    assert len(result.facts) == 1
    assert result.facts[0].metric == "revenue"
    assert result.facts[0].value == 100
    assert result.facts[0].filed_at == date(2025, 5, 22)
    assert any(issue.code == "ALIAS_VALUE_CONFLICT" for issue in result.issues)
    reversed_payload = facts_payload()
    reversed_payload["facts"]["us-gaap"] = dict(
        reversed(list(reversed_payload["facts"]["us-gaap"].items()))
    )
    assert fetch(reversed_payload).facts[0].value == 100


def test_restatement_vintages_and_durations_are_preserved() -> None:
    payload = facts_payload()
    rows = payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
    rows.extend(
        [
            {**row(120), "filed": "2025-06-01", "accn": "synthetic-002", "form": "10-Q/A"},
            {**row(250), "start": "2024-10-01"},
        ]
    )
    result = fetch(payload)
    assert len(result.facts) == 3
    assert {fact.value for fact in result.facts} == {100, 120, 250}


def test_exact_duplicates_are_recorded_and_conflicts_fail() -> None:
    payload = facts_payload()
    rows = payload["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"][
        "units"
    ]["USD"]
    rows.append(copy.deepcopy(rows[0]))
    assert any(i.code == "DUPLICATE_SOURCE_FACT" for i in fetch(payload).issues)
    rows[-1]["val"] = 999
    with pytest.raises(DataValidationError):
        fetch(payload)


def test_unknown_concepts_and_units_are_not_guessed() -> None:
    payload = {
        "cik": 123,
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"EUR": [row()]}},
                "UnregisteredExample": {"units": {"USD": [row()]}},
            }
        },
    }
    result = fetch(payload)
    assert result.facts == ()
    assert any(i.code == "UNSUPPORTED_UNIT" for i in result.issues)
    assert len(METRIC_REGISTRY) == 10


@pytest.mark.parametrize("mutation", ["missing", "chronology", "cik", "instant"])
def test_invalid_companyfacts_fail(mutation: str) -> None:
    payload = facts_payload()
    if mutation == "cik":
        payload["cik"] = 999
    else:
        entry = payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"][0]
        if mutation == "missing":
            del entry["filed"]
        elif mutation == "chronology":
            entry["filed"] = "2025-01-01"
        else:
            del entry["start"]
    with pytest.raises(DataValidationError):
        fetch(payload)


def test_conflicting_duplicates_in_lower_priority_alias_also_fail() -> None:
    payload = facts_payload()
    payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append(row(91))
    with pytest.raises(DataValidationError):
        fetch(payload)
