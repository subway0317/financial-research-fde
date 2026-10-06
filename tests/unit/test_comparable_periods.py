from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from financial_research.exceptions import PITViolationError
from financial_research.fundamentals.registry import METRIC_REGISTRY, MetricKind
from financial_research.schemas.fundamentals import FundamentalObservation
from financial_research.schemas.periods import FiscalPeriod, PeriodFrequency
from financial_research.schemas.tools import CalculationProvenance, EvidenceKind, EvidenceReference
from financial_research.tools.comparison import select_comparable_pair


def fact(
    year: int,
    quarter: int | None = 1,
    *,
    metric: str = "revenue",
    value="100",
    frequency: PeriodFrequency = PeriodFrequency.QUARTERLY,
) -> FundamentalObservation:
    end = date(year, quarter * 3, 30) if quarter else date(year, 12, 31)
    start = date(year, (quarter - 1) * 3 + 1, 1) if quarter else date(year, 1, 1)
    if METRIC_REGISTRY[metric].metric_kind == MetricKind.STOCK:
        start = None
    return FundamentalObservation(
        ticker="ABC",
        metric=metric,
        value=value,
        unit="USD",
        period_start=start,
        period_end=end,
        filed_at=date(2025, 5, 22),
        available_date=date(2025, 5, 23),
        form="10-Q",
        accession_number=f"synthetic-{year}-{quarter}",
        provider="fixture",
        source_reference=f"fixture://fact/{metric}/{year}/{quarter}",
        retrieved_at=datetime(2025, 6, 1, tzinfo=UTC),
        data_vintage="synthetic-v1",
        fiscal_period=FiscalPeriod(
            frequency=frequency,
            fiscal_year=year + 1,
            fiscal_quarter=quarter,
            source_reference="fixture://fiscal-labels",
        ),
    )


def test_registry_flow_and_stock() -> None:
    assert sum(m.metric_kind == MetricKind.FLOW for m in METRIC_REGISTRY.values()) == 6
    assert sum(m.metric_kind == MetricKind.STOCK for m in METRIC_REGISTRY.values()) == 4


@pytest.mark.parametrize("metric", ["revenue", "cash_and_equivalents"])
def test_quarterly_same_fiscal_quarter_prior_year(metric: str) -> None:
    prior, current = fact(2024, metric=metric), fact(2025, metric=metric)
    wrong_quarter = fact(2024, quarter=2, metric=metric)
    pair = select_comparable_pair((prior, wrong_quarter, current), metric, date(2025, 5, 25))
    assert pair.current == current
    assert pair.prior == prior
    assert pair.current.fiscal_period.fiscal_year == 2026
    assert pair.prior.fiscal_period.fiscal_year == 2025


@pytest.mark.parametrize("metric", ["revenue", "cash_and_equivalents"])
def test_annual_same_frequency_prior_year(metric: str) -> None:
    prior = fact(2023, None, metric=metric, frequency=PeriodFrequency.ANNUAL)
    current = fact(2024, None, metric=metric, frequency=PeriodFrequency.ANNUAL)
    quarter = fact(2023, quarter=4, metric=metric)
    pair = select_comparable_pair((prior, current, quarter), metric, date(2025, 5, 25))
    assert pair.current == current
    assert pair.prior == prior


def test_quarter_and_annual_cannot_be_mixed() -> None:
    current = fact(2025)
    annual = fact(2024, None, frequency=PeriodFrequency.ANNUAL)
    pair = select_comparable_pair((current, annual), "revenue", date(2025, 5, 25))
    assert pair.prior is None
    assert pair.reason == "NO_COMPARABLE_PRIOR_PERIOD"


def test_missing_period_metadata_never_guesses() -> None:
    current = fact(2025).model_copy(update={"fiscal_period": None})
    pair = select_comparable_pair((fact(2024), current), "revenue", date(2025, 5, 25))
    assert pair.reason == "UNVERIFIED_FISCAL_PERIOD"
    assert pair.prior is None


def test_selected_future_observation_is_integrity_failure() -> None:
    future = fact(2025).model_copy(update={"available_date": date(2025, 5, 27)})
    with pytest.raises(PITViolationError):
        select_comparable_pair((fact(2024), future), "revenue", date(2025, 5, 25))


def test_evidence_and_calculation_are_typed() -> None:
    source = EvidenceReference(
        evidence_id="fact-1",
        kind=EvidenceKind.SOURCE_FACT,
        metric="revenue",
        provider="fixture",
        source_reference="fixture://1",
    )
    computed = EvidenceReference(
        evidence_id="calc-1",
        kind=EvidenceKind.COMPUTATION,
        metric="revenue",
        provider="deterministic-python",
        source_reference="calculation://calc-1",
    )
    calculation = CalculationProvenance(
        evidence_id=computed.evidence_id,
        calculation_name="absolute_change",
        formula="current - prior",
        input_evidence_ids=(source.evidence_id, "fact-2"),
    )
    assert calculation.input_evidence_ids == ("fact-1", "fact-2")
    with pytest.raises(ValidationError):
        EvidenceReference.model_validate({**source.model_dump(), "kind": "INTERPRETATION"})


def test_ytd_cannot_be_labeled_as_quarterly() -> None:
    current = fact(2025)
    with pytest.raises(ValidationError):
        FundamentalObservation.model_validate(
            {**current.model_dump(), "period_start": "2024-10-01"}
        )
