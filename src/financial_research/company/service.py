"""Company capability depends only on canonical provider output."""

from pydantic import ValidationError

from financial_research.exceptions import DataValidationError
from financial_research.providers.base import CompanyProvider
from financial_research.schemas.base import canonical_ticker
from financial_research.schemas.company import CompanyProfile


class CompanyService:
    def __init__(self, provider: CompanyProvider) -> None:
        self._provider = provider

    def resolve(self, ticker: str) -> CompanyProfile:
        try:
            ticker = canonical_ticker(ticker)
            company = self._provider.get_company(ticker)
            company = CompanyProfile.model_validate(company.model_dump())
        except ValidationError as exc:
            raise DataValidationError("invalid canonical company") from exc
        except ValueError as exc:
            raise DataValidationError("invalid ticker") from exc
        if company.ticker != ticker:
            raise DataValidationError("company provider returned a different ticker")
        return company
