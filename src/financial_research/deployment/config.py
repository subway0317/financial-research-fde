"""Centralized runtime settings; missing credentials affect readiness, never liveness."""

import math
import os
import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError


class DeploymentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    environment: Literal["development", "test", "production"] = "production"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    port: int = Field(default=10000, ge=1, le=65535)
    openai_key: SecretStr | None = None
    openai_model: SecretStr | None = None
    openai_timeout_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    sec_user_agent: SecretStr | None = None
    demo_access_token: SecretStr | None = None
    commit: str = "unknown"

    @classmethod
    def from_env(cls) -> Self:
        def secret(name: str) -> SecretStr | None:
            value = os.environ.get(name)
            return SecretStr(value) if value and value.strip() else None

        timeout: float | None = None
        try:
            parsed = float(os.environ.get("OPENAI_TIMEOUT_SECONDS", ""))
            if math.isfinite(parsed) and parsed > 0:
                timeout = parsed
        except ValueError:
            pass
        commit = os.environ.get("RENDER_GIT_COMMIT", "")
        try:
            return cls(
                environment=os.environ.get("APP_ENV", "production"),
                log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
                port=int(os.environ.get("PORT", "10000")),
                openai_key=secret("OPENAI_API_KEY"),
                openai_model=secret("OPENAI_MODEL"),
                openai_timeout_seconds=timeout,
                sec_user_agent=secret("SEC_USER_AGENT"),
                demo_access_token=secret("DEMO_ACCESS_TOKEN"),
                commit=commit if re.fullmatch(r"[0-9a-fA-F]{7,64}", commit) else "unknown",
            )
        except (ValidationError, ValueError):
            raise ValueError("Invalid deployment configuration.") from None

    def readiness_codes(self) -> list[str]:
        fields = (
            (self.openai_key, "OPENAI_KEY_UNAVAILABLE"),
            (self.openai_model, "OPENAI_MODEL_UNAVAILABLE"),
            (self.openai_timeout_seconds, "OPENAI_TIMEOUT_UNAVAILABLE"),
            (self.sec_user_agent, "SEC_CONFIG_UNAVAILABLE"),
        )
        codes = [code for value, code in fields if not value]
        if self.environment == "production" and not self.demo_access_token:
            codes.append("DEMO_ACCESS_UNAVAILABLE")
        return codes
