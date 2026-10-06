from datetime import date

import httpx
import pytest

from financial_research.exceptions import DataValidationError, ProviderError
from financial_research.skills.smoke import run_live_composite_smoke
from financial_research.tools.smoke import SmokeStatus


def test_composite_smoke_structural_assertions_with_injected_fixture(fiscal_context) -> None:
    class Fixture:
        def build(self, **kwargs):
            return fiscal_context

    result = run_live_composite_smoke(
        ticker="NVDA", as_of_date=fiscal_context.as_of_date, builder=Fixture()
    )
    assert result.status == SmokeStatus.PASS
    assert result.context_build_count == 1
    assert result.skill_status == "PARTIAL"
    assert result.synthesis_readiness == "READY_WITH_WARNINGS"
    assert result.evidence_integrity
    assert len(result.subskills_executed) == 4


@pytest.mark.parametrize(
    "exception,expected",
    [
        (DataValidationError("invalid source"), SmokeStatus.FAILED),
        (ProviderError("unclassified failure"), SmokeStatus.FAILED),
        (ProviderError("external request failed"), SmokeStatus.EXTERNAL_BLOCKED),
    ],
)
def test_composite_smoke_external_blocks_remain_distinct(exception, expected) -> None:
    if expected == SmokeStatus.EXTERNAL_BLOCKED:
        request = httpx.Request("GET", "https://data.sec.gov/example")
        exception.__cause__ = httpx.HTTPStatusError(
            "outage", request=request, response=httpx.Response(503, request=request)
        )

    class Broken:
        def build(self, **kwargs):
            raise exception

    result = run_live_composite_smoke(ticker="NVDA", as_of_date=date(2026, 6, 30), builder=Broken())
    assert result.status == expected
    assert result.skill_status == "FAILED"
    assert result.synthesis_readiness == "NOT_READY"
    assert not result.evidence_integrity
    if expected == SmokeStatus.EXTERNAL_BLOCKED:
        assert result.http_status == 503
        assert result.provider_host == "data.sec.gov"
