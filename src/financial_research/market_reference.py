"""Versioned local metadata for the explicit Stage 8 U.S. USD equity universe.

Currency is a product contract, not a field supplied by Tiingo. Exchange hours
establish ET; America/New_York represents ET with IANA daylight-saving rules.
New codes require manual source verification, review, tests and a version bump.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from types import MappingProxyType

from financial_research.exceptions import DataValidationError

REGISTRY_VERSION = "us-exchanges-v1"
PRODUCT_CONTRACT_VERSION = "stage8-us-usd-equities-v1"
PRODUCT_SCOPE = "U.S.-listed, USD-quoted equities on explicitly supported U.S. exchanges"
REFERENCE_REVIEWED_ON = "2026-10-07"
IANA_REFERENCE = "https://data.iana.org/time-zones/tzdb/northamerica"


@dataclass(frozen=True)
class ExchangeReference:
    canonical_exchange: str
    currency: str
    timezone: str
    supported: bool
    sources: tuple[str, ...]


EXCHANGE_REGISTRY = MappingProxyType(
    {
        "NASDAQ": ExchangeReference(
            canonical_exchange="The Nasdaq Stock Market",
            currency="USD",
            timezone="America/New_York",
            supported=True,
            sources=(
                "https://www.nasdaq.com/market-activity/stock-market-holiday-schedule",
                IANA_REFERENCE,
            ),
        ),
        "NYSE": ExchangeReference(
            canonical_exchange="New York Stock Exchange",
            currency="USD",
            timezone="America/New_York",
            supported=True,
            sources=("https://www.nyse.com/trade/hours-calendars", IANA_REFERENCE),
        ),
    }
)
REGISTRY_HASH = hashlib.sha256(
    json.dumps(
        {
            "version": REGISTRY_VERSION,
            "product_contract": PRODUCT_CONTRACT_VERSION,
            "scope": PRODUCT_SCOPE,
            "reviewed_on": REFERENCE_REVIEWED_ON,
            "exchanges": {code: asdict(entry) for code, entry in EXCHANGE_REGISTRY.items()},
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()


def resolve_exchange(code: object) -> ExchangeReference:
    # Exact provider codes only: no case repair, aliases, learning or fallback.
    if not isinstance(code, str) or code not in EXCHANGE_REGISTRY:
        raise DataValidationError("unsupported market exchange metadata")
    entry = EXCHANGE_REGISTRY[code]
    if not entry.supported:
        raise DataValidationError("unsupported market exchange metadata")
    return entry
