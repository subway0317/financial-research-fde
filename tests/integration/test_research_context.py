from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from financial_research.exceptions import UnknownTickerError
from financial_research.schemas.provenance import SourceType
from financial_research.schemas.quality import QualityStatus
from financial_research.schemas.research import ResearchContext


def test_nvda_end_to_end_frozen_business_content(nvda_context, provider_payloads) -> None:
    context = nvda_context
    expected = provider_payloads["expected"]
    assert context.ticker == expected["ticker"]
    assert context.as_of_date.isoformat() == expected["as_of_date"]
    assert context.company.cik == "0001045810"
    assert len(context.market.observations) == expected["market_count"]
    assert context.market.observations[-1].date.isoformat() == expected["latest_market_date"]
    assert len(context.fundamentals.observations) == expected["fundamental_count"]
    revenue = next(o for o in context.fundamentals.observations if o.metric == "revenue")
    assert revenue.value == Decimal(expected["revenue"])
    assert revenue.available_date.isoformat() == expected["available_date"]
    assert context.quality.status.value == expected["quality_status"]
    for name, value in expected["latest_features"].items():
        assert getattr(context.market.features[-1], name) == pytest.approx(value)
    assert all(o.available_date <= context.as_of_date for o in context.fundamentals.observations)
    assert {p.source_type for p in context.provenance} == {
        SourceType.SOURCE_FACT,
        SourceType.COMPUTED_RESULT,
    }
    assert any(i.code == "PIT_EXCLUDED" for i in context.quality.issues)
    assert ResearchContext.model_validate_json(context.model_dump_json()) == context


def test_reproducibility_retains_data_vintage(fixture_builder) -> None:
    first = fixture_builder.build(ticker=" nvda ", as_of_date=date(2025, 5, 25))
    second = fixture_builder.build(ticker="NVDA", as_of_date=date(2025, 5, 25))
    assert first.generated_at != second.generated_at
    assert first.normalized_business_json() == second.normalized_business_json()
    assert "data_vintage" in first.normalized_business_json()
    assert "generated_at" not in first.normalized_business_json()
    assert "retrieved_at" not in first.normalized_business_json()


def test_core_is_not_nvda_specific(fixture_builder, provider_payloads) -> None:
    provider_payloads["market"]["chart"]["result"][0]["meta"]["symbol"] = "ACME"
    provider_payloads["fundamentals"]["cik"] = 1234567
    context = fixture_builder.build(ticker=" acme ", as_of_date=date(2025, 5, 25))
    assert context.company.company_name == "ACME (synthetic fixture)"
    assert context.ticker == "ACME"
    assert all(o.ticker == "ACME" for o in context.fundamentals.observations)


def test_unknown_ticker_is_explicit(fixture_builder) -> None:
    with pytest.raises(UnknownTickerError):
        fixture_builder.build(ticker="UNKNOWN", as_of_date=date(2025, 5, 25))


def test_asof_before_and_on_availability(fixture_builder) -> None:
    before = fixture_builder.build(ticker="NVDA", as_of_date=date(2025, 5, 22))
    on = fixture_builder.build(ticker="NVDA", as_of_date=date(2025, 5, 23))
    assert before.fundamentals.observations == ()
    assert len(on.fundamentals.observations) == 10
    assert on.quality.status == QualityStatus.PASS_WITH_WARNINGS


def test_revision_is_not_backfilled(fixture_builder, provider_payloads) -> None:
    earlier = fixture_builder.build(ticker="NVDA", as_of_date=date(2025, 5, 25))
    result = provider_payloads["market"]["chart"]["result"][0]
    result["timestamp"].append(int(datetime(2025, 5, 27, 13, 30, tzinfo=UTC).timestamp()))
    for values in result["indicators"]["quote"][0].values():
        values.append(values[-1])
    result["indicators"]["adjclose"][0]["adjclose"].append(
        result["indicators"]["adjclose"][0]["adjclose"][-1]
    )
    later = fixture_builder.build(ticker="NVDA", as_of_date=date(2025, 5, 27))
    assert {o.value for o in earlier.fundamentals.observations if o.metric == "revenue"} == {1000}
    revenue = [o for o in later.fundamentals.observations if o.metric == "revenue"]
    assert {o.value for o in revenue} == {1000, 1200}
    assert revenue[-1].available_date == date(2025, 5, 27)


def test_context_clock_changes_only_runtime_metadata(fixture_builder) -> None:
    first = fixture_builder.build(ticker="NVDA", as_of_date=date(2025, 5, 25))
    alternate = type(fixture_builder)(
        company_service=fixture_builder._company,
        market_service=fixture_builder._market,
        fundamental_service=fixture_builder._fundamentals,
        clock=lambda: datetime(2040, 1, 1, tzinfo=UTC),
    )
    second = alternate.build(ticker="NVDA", as_of_date=date(2025, 5, 25))
    assert second.generated_at.year == 2040
    assert first.normalized_business_json() == second.normalized_business_json()


def test_builder_does_not_hide_provider_validation_failure(
    fixture_builder, provider_payloads
) -> None:
    from financial_research.exceptions import DataValidationError

    del provider_payloads["fundamentals"]["cik"]
    with pytest.raises(DataValidationError):
        fixture_builder.build(ticker="NVDA", as_of_date=date(2025, 5, 25))
