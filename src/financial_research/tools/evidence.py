"""Stable grounding IDs and explicit calculation inputs; no runtime metadata in IDs."""

import hashlib
import json
from datetime import date
from decimal import Decimal

from financial_research.schemas.fundamentals import FundamentalObservation
from financial_research.schemas.market import MarketBar, MarketMetadata
from financial_research.schemas.tools import (
    CalculationParameter,
    CalculationProvenance,
    EvidenceKind,
    EvidenceReference,
)


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def fundamental_evidence(observation: FundamentalObservation) -> EvidenceReference:
    payload = observation.model_dump(mode="json", exclude={"retrieved_at"})
    return EvidenceReference(
        evidence_id=f"fact:{_digest(payload)}",
        kind=EvidenceKind.SOURCE_FACT,
        metric=observation.metric,
        provider=observation.provider,
        source_reference=observation.source_reference,
        period_start=observation.period_start,
        period_end=observation.period_end,
        filed_at=observation.filed_at,
        available_date=observation.available_date,
        value=str(observation.value),
        unit=observation.unit,
        data_vintage=observation.data_vintage,
        transformation=observation.transformation,
    )


def market_evidence(
    bar: MarketBar, metadata: MarketMetadata, field: str = "close"
) -> EvidenceReference:
    if field not in {"close", "high", "low"}:
        raise ValueError("unregistered market evidence field")
    reference = f"{metadata.provenance.source_reference}#session={bar.date}&field={field}"
    value = str(getattr(bar, field))
    return EvidenceReference(
        evidence_id=f"fact:{
            _digest(
                (bar.ticker, field, bar.date, value, reference, metadata.provenance.data_vintage)
            )
        }",
        kind=EvidenceKind.SOURCE_FACT,
        metric=field,
        provider=bar.provider,
        source_reference=reference,
        date=bar.date,
        value=value,
        unit=metadata.currency,
        data_vintage=metadata.provenance.data_vintage,
        transformation=metadata.provenance.transformation,
    )


def computation(
    *,
    name: str,
    metric: str,
    formula: str,
    inputs: tuple[EvidenceReference, ...],
    value: Decimal | float,
    parameters: tuple[CalculationParameter, ...] = (),
    session: date | None = None,
) -> tuple[EvidenceReference, CalculationProvenance]:
    input_ids = tuple(e.evidence_id for e in inputs)
    identity = _digest(
        (
            name,
            metric,
            formula,
            input_ids,
            [p.model_dump(mode="json") for p in parameters],
            str(value),
            session,
        )
    )
    evidence_id = f"computation:{identity}"
    return EvidenceReference(
        evidence_id=evidence_id,
        kind=EvidenceKind.COMPUTATION,
        metric=metric,
        provider="deterministic-python",
        source_reference=f"calculation://{identity}",
        date=session,
        value=str(value),
        transformation=(formula,),
    ), CalculationProvenance(
        evidence_id=evidence_id,
        calculation_name=name,
        formula=formula,
        input_evidence_ids=input_ids,
        parameters=parameters,
    )


def unique_evidence(references: tuple[EvidenceReference, ...]) -> tuple[EvidenceReference, ...]:
    return tuple({reference.evidence_id: reference for reference in references}.values())
