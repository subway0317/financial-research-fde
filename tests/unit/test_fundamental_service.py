from datetime import UTC, date, datetime

import pytest

from financial_research.exceptions import DataValidationError, UnsupportedMetricError
from financial_research.fundamentals.pit import ObservedSessionCalendar
from financial_research.fundamentals.service import FundamentalService
from financial_research.schemas.company import CompanyProfile
from financial_research.schemas.fundamentals import FundamentalSourceDataset, SourceFundamentalFact
from financial_research.schemas.provenance import ProvenanceRecord, SourceType


class FixtureProvider:
    def __init__(self, fact_updates: dict | None = None):
        self.updates = fact_updates or {}

    def get_fundamentals(self, company: CompanyProfile) -> FundamentalSourceDataset:
        facts = tuple(
            SourceFundamentalFact.model_validate(
                {
                    "ticker": company.ticker,
                    "metric": "revenue",
                    "value": "100",
                    "unit": "USD",
                    "period_start": "2025-01-01",
                    "period_end": "2025-03-31",
                    "filed_at": filing,
                    "form": "10-Q",
                    "accession_number": f"synthetic-{index}",
                    "provider": "fixture",
                    "source_reference": "fixture://fundamentals",
                    "retrieved_at": company.provenance.retrieved_at,
                    "data_vintage": "v1",
                    **self.updates,
                }
            )
            for index, filing in enumerate(("2025-05-21", "2025-05-22", "2025-05-23", "2025-05-28"))
        )
        return FundamentalSourceDataset(facts=facts, provenance=company.provenance)


def company() -> CompanyProfile:
    return CompanyProfile(
        ticker="ABC",
        company_name="ABC Corp",
        cik="123",
        exchange="X",
        currency="USD",
        provenance=ProvenanceRecord(
            provider="fixture",
            source_type=SourceType.SOURCE_FACT,
            source_reference="fixture://company",
            retrieved_at=datetime(2025, 6, 1, tzinfo=UTC),
            data_vintage="v1",
        ),
    )


def calendar() -> ObservedSessionCalendar:
    return ObservedSessionCalendar(
        coverage_start=date(2025, 5, 22),
        coverage_end=date(2025, 5, 25),
        sessions=(date(2025, 5, 22), date(2025, 5, 23)),
    )


def test_scope_and_asof_exclusions_have_records() -> None:
    result = FundamentalService(FixtureProvider()).get(company(), date(2025, 5, 25), calendar())
    assert len(result.observations) == 1
    assert result.observations[0].filed_at == date(2025, 5, 22)
    assert result.observations[0].available_date == date(2025, 5, 23)
    codes = [issue.code for issue in result.issues]
    assert codes.count("HISTORICAL_OUT_OF_SCOPE") == 1
    assert codes.count("PIT_EXCLUDED") == 2
    assert codes.count("MISSING_METRIC") == 9


@pytest.mark.parametrize("updates", [{"ticker": "OTHER"}, {"unit": "EUR"}])
def test_canonical_contract_mismatch_fails(updates: dict) -> None:
    with pytest.raises(DataValidationError):
        FundamentalService(FixtureProvider(updates)).get(company(), date(2025, 5, 25), calendar())


def test_unsupported_canonical_metric_is_explicit() -> None:
    with pytest.raises(UnsupportedMetricError):
        FundamentalService(FixtureProvider({"metric": "not_registered"})).get(
            company(), date(2025, 5, 25), calendar()
        )
