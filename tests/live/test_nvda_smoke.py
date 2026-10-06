"""Opt-in real provider requests. External blocks are reported, never skipped or mocked."""

import os
from datetime import date

import pytest

from financial_research.tools.smoke import SmokeStatus, run_live_smoke


@pytest.mark.live
def test_nvda_live_smoke() -> None:
    as_of_date = date.fromisoformat(os.environ.get("LIVE_AS_OF_DATE", "2026-06-30"))
    result = run_live_smoke(ticker="NVDA", as_of_date=as_of_date)
    print(result.model_dump_json(indent=2))
    assert result.status == SmokeStatus.PASS, result.model_dump_json()
