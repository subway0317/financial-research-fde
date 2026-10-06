"""Canonical company identity (reference metadata, not historical security master)."""

from financial_research.schemas.base import CIK, CanonicalModel, NonEmpty, Ticker
from financial_research.schemas.provenance import ProvenanceRecord


class CompanyProfile(CanonicalModel):
    ticker: Ticker
    company_name: NonEmpty
    cik: CIK
    exchange: NonEmpty
    currency: str | None = None
    provenance: ProvenanceRecord
