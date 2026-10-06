"""Source evidence is distinct from deterministic transformations."""

from enum import StrEnum

from pydantic import AwareDatetime

from financial_research.schemas.base import CanonicalModel, NonEmpty


class SourceType(StrEnum):
    SOURCE_FACT = "SOURCE_FACT"
    COMPUTED_RESULT = "COMPUTED_RESULT"


class ProvenanceRecord(CanonicalModel):
    provider: NonEmpty
    source_type: SourceType
    source_reference: NonEmpty
    retrieved_at: AwareDatetime
    data_vintage: NonEmpty
    transformation: tuple[str, ...] = ()
    content_hash: str | None = None
