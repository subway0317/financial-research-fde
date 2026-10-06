"""SEC EDGAR identity adapter (companyfacts normalization is separate capability)."""

import logging

import httpx
from pydantic import ValidationError

from financial_research.exceptions import DataValidationError, UnknownTickerError
from financial_research.providers.http import JsonTransport
from financial_research.providers.sec_facts import normalize_companyfacts
from financial_research.schemas.base import canonical_ticker
from financial_research.schemas.company import CompanyProfile
from financial_research.schemas.fundamentals import FundamentalSourceDataset

logger = logging.getLogger(__name__)
DIRECTORY_URL = "https://www.sec.gov/files/company_tickers_exchange.json"


class SECProvider:
    def __init__(
        self, *, user_agent: str, client: httpx.Client | None = None, timeout: float = 30
    ) -> None:
        if not user_agent.strip() or "@" not in user_agent:
            raise DataValidationError("SEC requires an explicit User-Agent with contact email")
        self._transport = JsonTransport(
            "sec-edgar",
            client=client,
            timeout=timeout,
            user_agent=user_agent,
            minimum_interval=0.11,
        )

    def close(self) -> None:
        self._transport.close()

    def get_company(self, ticker: str) -> CompanyProfile:
        try:
            ticker = canonical_ticker(ticker)
        except ValueError as exc:
            raise DataValidationError("invalid company ticker") from exc
        response = self._transport.get(DIRECTORY_URL)
        try:
            fields = response.payload["fields"]
            rows = response.payload["data"]
            if not isinstance(fields, list) or not isinstance(rows, list):
                raise ValueError("invalid directory arrays")
            if len(set(fields)) != len(fields) or not {"cik", "name", "ticker", "exchange"} <= set(
                fields
            ):
                raise ValueError("invalid directory fields")
            matches = []
            for row in rows:
                if not isinstance(row, list) or len(row) != len(fields):
                    raise ValueError("invalid directory row")
                record = dict(zip(fields, row, strict=True))
                if canonical_ticker(record["ticker"]) == ticker:
                    matches.append(record)
            if not matches:
                raise UnknownTickerError(f"SEC directory cannot resolve {ticker}")
            if len(matches) != 1:
                raise ValueError("ambiguous ticker mapping")
            match = matches[0]
            company = CompanyProfile(
                ticker=ticker,
                company_name=match["name"],
                cik=str(match["cik"]),
                exchange=match["exchange"],
                currency=None,
                provenance=response.provenance.model_copy(
                    update={
                        "transformation": (
                            "SEC directory identity normalization; currency unknown",
                        )
                    }
                ),
            )
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise DataValidationError("SEC directory failed canonical normalization") from exc
        logger.info("company normalized ticker=%s", ticker)
        return company

    def get_fundamentals(self, company: CompanyProfile) -> FundamentalSourceDataset:
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{company.cik}.json"
        return normalize_companyfacts(company, self._transport.get(url))
