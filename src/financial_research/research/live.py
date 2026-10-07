"""Explicit live composition with per-build resource ownership; no framework imports."""

from contextlib import ExitStack
from datetime import date, timedelta

from financial_research.company.service import CompanyService
from financial_research.config import ResearchConfig
from financial_research.exceptions import ConfigurationError
from financial_research.fundamentals.service import FundamentalService
from financial_research.market.service import MarketService
from financial_research.providers.market import YahooMarketProvider
from financial_research.providers.sec import SECProvider
from financial_research.providers.tiingo import TiingoMarketProvider
from financial_research.research.context import ResearchContextBuilder
from financial_research.schemas.research import ResearchContext


def create_market_provider(config: ResearchConfig) -> YahooMarketProvider | TiingoMarketProvider:
    if config.market_data_provider == "yahoo":
        return YahooMarketProvider(timeout=config.http_timeout_seconds)
    token = config.tiingo_api_token
    if token is None or not token.get_secret_value().strip():
        raise ConfigurationError("TIINGO_API_TOKEN must be configured for Tiingo")
    return TiingoMarketProvider(
        api_token=token.get_secret_value(), timeout=config.http_timeout_seconds
    )


class LiveContextBuilder:
    def __init__(self, config: ResearchConfig | None = None) -> None:
        self._config = config or ResearchConfig.from_env()

    def build(self, *, ticker: str, as_of_date: date) -> ResearchContext:
        config = self._config
        if not config.sec_user_agent:
            raise ConfigurationError("SEC_USER_AGENT must be configured for live research")
        with ExitStack() as stack:
            market = create_market_provider(config)
            stack.callback(market.close)
            sec = SECProvider(
                user_agent=config.sec_user_agent,
                timeout=config.http_timeout_seconds,
                fiscal_metadata_start=as_of_date - timedelta(days=config.market_lookback_days),
                fiscal_metadata_end=as_of_date,
            )
            stack.callback(sec.close)
            return ResearchContextBuilder(
                company_service=CompanyService(sec),
                market_service=MarketService(market),
                fundamental_service=FundamentalService(sec),
                config=config,
            ).build(ticker=ticker, as_of_date=as_of_date)
