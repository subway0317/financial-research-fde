"""Typed synthesis size ceiling, independent of models and evaluation infrastructure."""

import os
import re
from typing import Annotated, Self

from pydantic import Field

from financial_research.llm.errors import AgentConfigurationError
from financial_research.schemas.base import CanonicalModel

DEFAULT_MAX_SYNTHESIS_PAYLOAD_BYTES = 200_000


class AgentRuntimeConfig(CanonicalModel):
    max_synthesis_payload_bytes: Annotated[int, Field(gt=0, strict=True)] = (
        DEFAULT_MAX_SYNTHESIS_PAYLOAD_BYTES
    )

    @classmethod
    def from_env(cls) -> Self:
        value = os.environ.get("MAX_SYNTHESIS_PAYLOAD_BYTES")
        if value is None:
            return cls()
        try:
            if not re.fullmatch(r"[0-9]+", value) or int(value) <= 0:
                raise ValueError
            return cls(max_synthesis_payload_bytes=int(value))
        except ValueError:
            raise AgentConfigurationError(
                "MAX_SYNTHESIS_PAYLOAD_BYTES must be a positive integer."
            ) from None
