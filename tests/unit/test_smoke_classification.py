import httpx
import pytest

from financial_research.exceptions import ProviderError
from financial_research.tools.smoke import SmokeStatus, provider_failure


@pytest.mark.parametrize(
    "status,expected",
    [
        (403, SmokeStatus.EXTERNAL_BLOCKED),
        (429, SmokeStatus.EXTERNAL_BLOCKED),
        (503, SmokeStatus.EXTERNAL_BLOCKED),
        (404, SmokeStatus.FAILED),
    ],
)
def test_external_blocks_are_not_implementation_success(status, expected) -> None:
    response = httpx.Response(status, request=httpx.Request("GET", "https://www.sec.gov/example"))
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as cause:
        error = ProviderError("fixture provider request failed")
        error.__cause__ = cause
    actual, actual_http, host = provider_failure(error)
    assert actual == expected
    assert actual_http == status
    assert host == "www.sec.gov"


def test_network_error_external_unclassified_error_fails() -> None:
    error = ProviderError("network unavailable")
    error.__cause__ = httpx.ConnectError("fixture connection failed")
    assert provider_failure(error)[0] == SmokeStatus.EXTERNAL_BLOCKED
    assert provider_failure(ProviderError("unclassified"))[0] == SmokeStatus.FAILED
