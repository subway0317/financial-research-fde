import copy
from datetime import date

import httpx
import pytest

from financial_research.exceptions import DataValidationError
from financial_research.providers.sec import SECProvider
from financial_research.providers.sec_periods import FilingMetadata, corroborated_period


def row() -> dict:
    return {
        "start": "2025-01-01",
        "end": "2025-03-31",
        "filed": "2025-05-22",
        "val": 100,
        "form": "10-Q",
        "accn": "synthetic-current",
        "fy": 2026,
        "fp": "Q2",
    }


def metadata():
    return {
        "synthetic-current": FilingMetadata(
            report_date=date(2025, 3, 31),
            filed_at=date(2025, 5, 22),
            form="10-Q",
            source_reference="fixture://submissions/current",
            data_vintage="synthetic-v1",
        )
    }


def test_sec_labels_require_primary_report_date_and_match_filing() -> None:
    descriptor = corroborated_period(row(), metadata())
    assert descriptor.frequency == "QUARTERLY"
    assert descriptor.fiscal_year == 2026
    assert descriptor.fiscal_quarter == 2
    # fy/fp still identify the 2026 filing, not this comparative 2024 fact.
    comparative = {**row(), "start": "2024-01-01", "end": "2024-03-31"}
    assert corroborated_period(comparative, metadata()) is None
    assert corroborated_period({**row(), "filed": "2025-05-23"}, metadata()) is None


def test_sec_ytd_and_missing_labels_are_not_guessed() -> None:
    assert corroborated_period({**row(), "start": "2024-10-01"}, metadata()) is None
    assert corroborated_period({**row(), "fy": None}, metadata()) is None
    assert corroborated_period(row(), {}) is None
    assert corroborated_period({**row(), "start": None}, metadata()).frequency == "QUARTERLY"


def test_annual_flow_and_stock_classification() -> None:
    meta = {
        "synthetic-current": FilingMetadata(
            report_date=date(2024, 12, 31),
            filed_at=date(2025, 5, 22),
            form="10-K",
            source_reference="fixture://submissions/annual",
            data_vintage="synthetic-v1",
        )
    }
    annual = {
        **row(),
        "start": "2024-01-01",
        "end": "2024-12-31",
        "fy": 2025,
        "fp": "FY",
        "form": "10-K",
    }
    assert corroborated_period(annual, meta).frequency == "ANNUAL"
    assert corroborated_period({**annual, "start": None}, meta).frequency == "ANNUAL"
    assert corroborated_period({**annual, "start": "2024-10-01"}, meta) is None


def test_optional_adapter_enrichment_fetches_only_in_scope_archives(nvda_context) -> None:
    current = row()
    comparative = {**current, "start": "2024-01-01", "end": "2024-03-31", "val": 90}
    prior = {**comparative, "filed": "2024-05-22", "accn": "synthetic-prior", "fy": 2025}
    facts = {
        "cik": 1045810,
        "facts": {"us-gaap": {"Revenues": {"units": {"USD": [current, comparative, prior]}}}},
    }
    recent = {
        "cik": "1045810",
        "filings": {
            "recent": {
                "accessionNumber": ["synthetic-current"],
                "reportDate": ["2025-03-31"],
                "filingDate": ["2025-05-22"],
                "form": ["10-Q"],
            },
            "files": [
                {
                    "name": "CIK0001045810-submissions-001.json",
                    "filingFrom": "2024-01-01",
                    "filingTo": "2024-12-31",
                },
                {
                    "name": "CIK0001045810-submissions-002.json",
                    "filingFrom": "2020-01-01",
                    "filingTo": "2020-12-31",
                },
            ],
        },
    }
    archive = {
        "accessionNumber": ["synthetic-prior"],
        "reportDate": ["2024-03-31"],
        "filingDate": ["2024-05-22"],
        "form": ["10-Q"],
    }
    requested = []

    def handler(request):
        requested.append(request.url.path)
        if "/companyfacts/" in request.url.path:
            return httpx.Response(200, json=facts)
        if request.url.path.endswith("-001.json"):
            return httpx.Response(200, json=archive)
        if request.url.path.endswith("/CIK0001045810.json"):
            return httpx.Response(200, json=recent)
        raise AssertionError("out-of-scope metadata archive must not be downloaded")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = SECProvider(
            user_agent="Fixture fixture@example.com",
            client=client,
            fiscal_metadata_start=date(2024, 1, 1),
            fiscal_metadata_end=date(2025, 5, 25),
        )
        normalized = provider.get_fundamentals(nvda_context.company)
    assert len(requested) == 3
    by_accession = [fact for fact in normalized.facts if fact.accession_number == "synthetic-prior"]
    assert by_accession[0].fiscal_period.fiscal_year == 2025
    assert (
        next(f for f in normalized.facts if f.period_end.year == 2025).fiscal_period.fiscal_year
        == 2026
    )
    assert (
        next(
            f
            for f in normalized.facts
            if f.accession_number == "synthetic-current" and f.period_end.year == 2024
        ).fiscal_period
        is None
    )


def test_invalid_submissions_are_explicit(nvda_context) -> None:
    bad = {
        "cik": 1045810,
        "filings": {
            "recent": {
                "accessionNumber": ["one"],
                "reportDate": [],
                "filingDate": ["2025-05-22"],
                "form": ["10-Q"],
            },
            "files": [],
        },
    }
    facts = {"cik": 1045810, "facts": {"us-gaap": {}}}
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=copy.deepcopy(bad) if "/submissions/" in request.url.path else facts
            )
        )
    ) as client:
        provider = SECProvider(
            user_agent="Fixture fixture@example.com",
            client=client,
            fiscal_metadata_start=date(2024, 1, 1),
            fiscal_metadata_end=date(2025, 5, 25),
        )
        with pytest.raises(DataValidationError):
            provider.get_fundamentals(nvda_context.company)
