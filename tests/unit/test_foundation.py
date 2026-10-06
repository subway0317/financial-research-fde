from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from financial_research.config import ResearchConfig
from financial_research.schemas.company import CompanyProfile
from financial_research.schemas.market import MarketBar
from financial_research.schemas.provenance import ProvenanceRecord, SourceType
from financial_research.schemas.quality import QualityIssue, QualityReport, QualityStatus, Severity


def provenance() -> ProvenanceRecord:
    return ProvenanceRecord(
        provider="fixture",
        source_type=SourceType.SOURCE_FACT,
        source_reference="fixture://company",
        retrieved_at=datetime.now(UTC),
        data_vintage="fixture-v1",
    )


def test_canonical_identity() -> None:
    company = CompanyProfile(
        ticker=" nvda ",
        company_name="NVIDIA",
        cik="1045810",
        exchange="Nasdaq",
        currency="USD",
        provenance=provenance(),
    )
    assert company.ticker == "NVDA"
    assert company.cik == "0001045810"
    assert ResearchConfig().market_lookback_days == 730


@pytest.mark.parametrize("ticker", ["", "bad ticker", "../path"])
def test_bad_ticker(ticker: str) -> None:
    with pytest.raises(ValidationError):
        CompanyProfile(
            ticker=ticker, company_name="Company", cik="1", exchange="X", provenance=provenance()
        )


@pytest.mark.parametrize("price", [float("nan"), float("inf"), 0, -1])
def test_required_prices_are_positive_and_finite(price: float) -> None:
    with pytest.raises(ValidationError):
        MarketBar(
            ticker="ABC",
            date=date(2025, 1, 2),
            open=price,
            high=10,
            low=1,
            close=5,
            volume=10,
            provider="fixture",
            retrieved_at=datetime.now(UTC),
        )


def test_missing_required_field_and_naive_timestamp() -> None:
    with pytest.raises(ValidationError):
        CompanyProfile.model_validate({"ticker": "ABC"})
    with pytest.raises(ValidationError):
        ProvenanceRecord(
            provider="fixture",
            source_type=SourceType.SOURCE_FACT,
            source_reference="fixture://x",
            retrieved_at=datetime(2025, 1, 1),
            data_vintage="v1",
        )


def test_quality_status_cannot_conceal_error() -> None:
    issue = QualityIssue(code="PIT_VIOLATION", severity=Severity.ERROR, message="future")
    assert QualityReport.from_issues((issue,)).status == QualityStatus.FAIL
    assert QualityReport.from_issues(()).status == QualityStatus.PASS
    with pytest.raises(ValidationError):
        QualityReport(status=QualityStatus.PASS, issues=(issue,))
