"""Common validation and identity types."""

import re
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def canonical_ticker(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("ticker must be a string")
    ticker = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,14}", ticker):
        raise ValueError("invalid ticker")
    return ticker


def canonical_cik(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("CIK must contain digits")
    text = str(value)
    if not text.isascii() or not text.isdigit() or len(text) > 10 or int(text) <= 0:
        raise ValueError("invalid CIK")
    return text.zfill(10)


Ticker = Annotated[str, BeforeValidator(canonical_ticker)]
CIK = Annotated[str, BeforeValidator(canonical_cik)]
NonEmpty = Annotated[str, Field(min_length=1, pattern=r"\S")]


class CanonicalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
