from datetime import date

import pytest

from financial_research.agent import smoke
from financial_research.agent.errors import AgentIntegrityError
from financial_research.exceptions import ProviderError
from financial_research.llm.errors import AgentConfigurationError, LLMProviderError
from financial_research.schemas.agent import ResearchAgentRequest

REQUEST = ResearchAgentRequest(
    question="How have NVDA's fundamentals changed?", ticker="NVDA", as_of_date=date(2026, 6, 30)
)


def test_smoke_missing_configuration_does_not_construct_clients(monkeypatch):
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "SEC_USER_AGENT"):
        monkeypatch.delenv(name, raising=False)

    def forbidden():
        raise AssertionError("configuration preflight must not construct a client")

    monkeypatch.setattr(smoke, "OpenAIResponsesClient", forbidden)
    result = smoke.run_live_agent_smoke(request=REQUEST)
    assert result.status == smoke.AgentSmokeStatus.USER_CONFIGURATION_REQUIRED
    assert result.missing_configuration == ("OPENAI_API_KEY", "OPENAI_MODEL", "SEC_USER_AGENT")
    assert result.llm_call_count == 0


@pytest.mark.parametrize(
    "error,status",
    [
        (AgentConfigurationError, smoke.AgentSmokeStatus.USER_CONFIGURATION_REQUIRED),
        (LLMProviderError, smoke.AgentSmokeStatus.EXTERNAL_BLOCKED),
        (ProviderError, smoke.AgentSmokeStatus.EXTERNAL_BLOCKED),
        (AgentIntegrityError, smoke.AgentSmokeStatus.FAIL),
        (RuntimeError, smoke.AgentSmokeStatus.FAIL),
    ],
)
def test_smoke_classifies_failure_without_provider_or_secret_leak(monkeypatch, error, status):
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "SEC_USER_AGENT"):
        monkeypatch.setenv(name, "offline-placeholder")

    def fail():
        raise error("private-diagnostic")

    monkeypatch.setattr(smoke, "OpenAIResponsesClient", fail)
    result = smoke.run_live_agent_smoke(request=REQUEST)
    assert result.status == status
    assert "private-diagnostic" not in result.model_dump_json()


def test_smoke_invalid_api_request_is_failure_rather_than_external_outage(monkeypatch):
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "SEC_USER_AGENT"):
        monkeypatch.setenv(name, "offline-placeholder")

    def fail():
        error = LLMProviderError()
        error.http_status = 400
        raise error

    monkeypatch.setattr(smoke, "OpenAIResponsesClient", fail)
    assert smoke.run_live_agent_smoke(request=REQUEST).status == smoke.AgentSmokeStatus.FAIL
