"""Vendor-neutral classification of session-level source evidence."""

import re

from financial_research.schemas.tools import EvidenceKind, EvidenceReference


def is_market_source(ref: EvidenceReference) -> bool:
    field = re.sub(r"[^a-z]", "", ref.metric.lower())
    fields = {"open", "high", "low", "close", "volume", "divcash", "splitfactor"}
    fields |= {prefix + name for prefix in ("adj", "adjusted", "raw") for name in fields}
    # Canonical session facts have date; SEC facts use period/filed/available dates.
    # Unknown session fields fail closed rather than depending on a vendor name.
    return ref.kind == EvidenceKind.SOURCE_FACT and (
        ref.date is not None or field in fields or "#session=" in ref.source_reference
    )
