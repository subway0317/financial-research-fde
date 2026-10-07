"""Small explicit configuration; no implicit .env loading or research clock."""

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from financial_research.exceptions import ConfigurationError

MarketDataProvider = Literal["yahoo", "tiingo"]


class ResearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sec_user_agent: str | None = None
    http_timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    market_lookback_days: int = Field(default=730, ge=90)
    stale_market_days: int = Field(default=7, ge=0)
    market_data_provider: MarketDataProvider = "yahoo"
    tiingo_api_token: SecretStr | None = None

    @classmethod
    def from_env(cls) -> "ResearchConfig":
        token = os.environ.get("TIINGO_API_TOKEN", "").strip()
        try:
            return cls(
                sec_user_agent=os.environ.get("SEC_USER_AGENT"),
                http_timeout_seconds=float(os.environ.get("HTTP_TIMEOUT_SECONDS", "30")),
                market_lookback_days=int(os.environ.get("MARKET_LOOKBACK_DAYS", "730")),
                stale_market_days=int(os.environ.get("STALE_MARKET_DAYS", "7")),
                market_data_provider=os.environ.get("MARKET_DATA_PROVIDER", "yahoo"),
                tiingo_api_token=SecretStr(token) if token else None,
            )
        except (ValidationError, ValueError):
            raise ConfigurationError("Invalid research configuration.") from None
