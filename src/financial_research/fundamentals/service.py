"""Canonical fundamentals capability; explicit scope and PIT exclusion records."""

from datetime import date

from pydantic import ValidationError

from financial_research.exceptions import DataValidationError
from financial_research.fundamentals.pit import (
    ObservedSessionCalendar,
    assert_pit_safe,
    next_observed_session,
    select_available,
)
from financial_research.fundamentals.registry import METRIC_REGISTRY, PeriodType, require_metric
from financial_research.providers.base import FundamentalProvider
from financial_research.schemas.company import CompanyProfile
from financial_research.schemas.fundamentals import (
    FundamentalObservation,
    FundamentalResearch,
    FundamentalSourceDataset,
)
from financial_research.schemas.quality import QualityIssue, Severity


class FundamentalService:
    def __init__(self, provider: FundamentalProvider) -> None:
        self._provider = provider

    def get(
        self, company: CompanyProfile, as_of_date: date, calendar: ObservedSessionCalendar
    ) -> FundamentalResearch:
        if calendar.coverage_end != as_of_date:
            raise DataValidationError("PIT calendar must end at the explicit as_of_date")
        source = self._provider.get_fundamentals(company)
        try:
            source = FundamentalSourceDataset.model_validate(source.model_dump())
        except ValidationError as exc:
            raise DataValidationError("invalid canonical fundamentals dataset") from exc
        issues = list(source.issues)
        observations = []
        for fact in source.facts:
            definition = require_metric(fact.metric)
            if fact.ticker != company.ticker or fact.unit != definition.unit:
                raise DataValidationError("fundamental ticker/unit mismatch")
            if (definition.period_type == PeriodType.DURATION) != (fact.period_start is not None):
                raise DataValidationError("fundamental duration/instant mismatch")
            if fact.filed_at < calendar.coverage_start:
                issues.append(
                    QualityIssue(
                        code="HISTORICAL_OUT_OF_SCOPE",
                        severity=Severity.INFO,
                        message="filing predates requested history; availability not fabricated",
                        affected_field=fact.metric,
                        affected_date=fact.filed_at,
                        affected_context=fact.accession_number,
                    )
                )
                continue
            available_date = next_observed_session(fact.filed_at, calendar)
            if available_date is None:
                issues.append(
                    QualityIssue(
                        code="PIT_EXCLUDED",
                        severity=Severity.INFO,
                        message="no post-filing session on/before as_of_date; fact unavailable",
                        affected_field=fact.metric,
                        affected_date=fact.filed_at,
                        affected_context=fact.accession_number,
                    )
                )
                continue
            observations.append(
                FundamentalObservation.model_validate(
                    {
                        **fact.model_dump(),
                        "available_date": available_date,
                        "transformation": (
                            *fact.transformation,
                            "daily PIT: strictly next observed market session after filed_at",
                        ),
                    }
                )
            )
        selected = select_available(tuple(observations), as_of_date)
        assert_pit_safe(selected, as_of_date)
        available_metrics = {observation.metric for observation in selected}
        for metric in METRIC_REGISTRY:
            if metric not in available_metrics:
                issues.append(
                    QualityIssue(
                        code="MISSING_METRIC",
                        severity=Severity.WARNING,
                        message="no legally available registered observation in requested scope",
                        affected_field=metric,
                    )
                )
        return FundamentalResearch(
            observations=selected,
            provenance=(source.provenance, *(o.provenance_record() for o in selected)),
            issues=tuple(issues),
        )
