"""Canonical provider protocols; raw payloads stay inside adapters."""

from datetime import date
from typing import Protocol

from financial_research.schemas.company import CompanyProfile
from financial_research.schemas.fundamentals import FundamentalSourceDataset
from financial_research.schemas.market import MarketDataset


class CompanyProvider(Protocol):
    def get_company(self, ticker: str) -> CompanyProfile: ...


class MarketProvider(Protocol):
    def get_market(self, ticker: str, start: date, end: date) -> MarketDataset: ...


class FundamentalProvider(Protocol):
    def get_fundamentals(self, company: CompanyProfile) -> FundamentalSourceDataset: ...
