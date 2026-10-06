"""Explicit real-provider composite path; never mocked, skipped or run by default."""

import os
from datetime import date

import pytest

from financial_research.skills.smoke import run_live_composite_smoke
from financial_research.tools.smoke import SmokeStatus


@pytest.mark.live
def test_nvda_equity_skill_live_smoke() -> None:
    result = run_live_composite_smoke(
        ticker="NVDA",
        as_of_date=date.fromisoformat(os.environ.get("LIVE_AS_OF_DATE", "2026-06-30")),
    )
    print(result.model_dump_json(indent=2))
    assert result.status == SmokeStatus.PASS, result.model_dump_json()
    assert result.context_build_count == 1
    assert result.evidence_integrity
