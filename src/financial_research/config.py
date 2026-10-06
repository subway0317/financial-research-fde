"""Small explicit configuration; no implicit .env loading or research clock."""

import os

from pydantic import BaseModel, ConfigDict, Field


class ResearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sec_user_agent: str | None = None
    http_timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    market_lookback_days: int = Field(default=730, ge=90)
    stale_market_days: int = Field(default=7, ge=0)

    @classmethod
    def from_env(cls) -> "ResearchConfig":
        return cls(
            sec_user_agent=os.environ.get("SEC_USER_AGENT"),
            http_timeout_seconds=float(os.environ.get("HTTP_TIMEOUT_SECONDS", "30")),
            market_lookback_days=int(os.environ.get("MARKET_LOOKBACK_DAYS", "730")),
            stale_market_days=int(os.environ.get("STALE_MARKET_DAYS", "7")),
        )
