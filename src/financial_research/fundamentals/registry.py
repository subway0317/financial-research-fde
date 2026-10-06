"""Small canonical universe; provider concept names do not belong here."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from financial_research.exceptions import UnsupportedMetricError


class PeriodType(StrEnum):
    DURATION = "DURATION"
    INSTANT = "INSTANT"


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    unit: str
    period_type: PeriodType
    meaning: str


METRIC_REGISTRY: Mapping[str, MetricDefinition] = MappingProxyType(
    {
        metric.name: metric
        for metric in (
            MetricDefinition("revenue", "USD", PeriodType.DURATION, "Reported revenue"),
            MetricDefinition("gross_profit", "USD", PeriodType.DURATION, "Reported gross profit"),
            MetricDefinition(
                "operating_income", "USD", PeriodType.DURATION, "Operating income/loss"
            ),
            MetricDefinition("net_income", "USD", PeriodType.DURATION, "Net income/loss"),
            MetricDefinition(
                "operating_cash_flow",
                "USD",
                PeriodType.DURATION,
                "Net cash provided by/used in operating activities",
            ),
            MetricDefinition(
                "capital_expenditures",
                "USD",
                PeriodType.DURATION,
                "Payments to acquire property, plant and equipment; positive outflow",
            ),
            MetricDefinition(
                "cash_and_equivalents",
                "USD",
                PeriodType.INSTANT,
                "Cash and cash equivalents at carrying value",
            ),
            MetricDefinition("total_assets", "USD", PeriodType.INSTANT, "Total assets"),
            MetricDefinition("total_liabilities", "USD", PeriodType.INSTANT, "Total liabilities"),
            MetricDefinition(
                "stockholders_equity",
                "USD",
                PeriodType.INSTANT,
                "Stockholders equity excluding noncontrolling interests",
            ),
        )
    }
)


def require_metric(name: str) -> MetricDefinition:
    try:
        return METRIC_REGISTRY[name]
    except KeyError as exc:
        raise UnsupportedMetricError(f"unregistered fundamental metric: {name}") from exc
