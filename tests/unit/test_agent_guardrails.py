import json
from datetime import date

import pytest
from pydantic import ValidationError

from financial_research.agent.config import AgentRuntimeConfig
from financial_research.agent.errors import PayloadBudgetExceeded
from financial_research.agent.evidence_projection import project_evidence
from financial_research.agent.planner import INTENT_REASONS, INTENT_SKILLS
from financial_research.agent.service import ResearchAgent
from financial_research.agent.synthesis_payload import synthesis_payload
from financial_research.llm.errors import AgentConfigurationError
from financial_research.llm.fake import FakeLLMClient
from financial_research.schemas.agent import AgentIntent, ResearchAgentRequest, ResponseLanguage
from financial_research.skills.defaults import create_skill_registry


def plan():
    intent = AgentIntent.BROAD_RESEARCH
    return {
        "plan_version": "1.0",
        "intent": intent,
        "selected_skill_id": INTENT_SKILLS[intent],
        "reason_code": INTENT_REASONS[intent],
        "ticker": "NVDA",
        "as_of_date": "2025-05-25",
        "requested_focus": None,
    }


def synthesis(request):
    projection = json.loads(request.user_payload)["projection"]
    return json.dumps(
        {
            "used_skill_ids": [projection["skill_id"]],
            "claims": [
                {
                    "claim_id": "c1",
                    "section": "FUNDAMENTALS",
                    "claim_type": "INTERPRETATION",
                    "statement": "Supplied evidence is available.",
                    "evidence_ids": [next(iter(projection["evidence_index"]))],
                }
            ],
        }
    )


def test_payload_config_default_and_override(monkeypatch):
    monkeypatch.delenv("MAX_SYNTHESIS_PAYLOAD_BYTES", raising=False)
    assert AgentRuntimeConfig.from_env().max_synthesis_payload_bytes == 200000
    monkeypatch.setenv("MAX_SYNTHESIS_PAYLOAD_BYTES", "180000")
    assert AgentRuntimeConfig.from_env().max_synthesis_payload_bytes == 180000


@pytest.mark.parametrize("value", ["", "0", "-1", "1.5", "nan", "inf", "true", "secret-invalid"])
def test_payload_config_errors_are_safe(monkeypatch, value):
    monkeypatch.setenv("MAX_SYNTHESIS_PAYLOAD_BYTES", value)
    with pytest.raises(AgentConfigurationError, match="positive integer") as failure:
        AgentRuntimeConfig.from_env()
    assert "secret-invalid" not in str(failure.value)


@pytest.mark.parametrize("value", [True, 0, -1, 1.5, float("inf")])
def test_payload_config_is_typed_positive_integer(value):
    with pytest.raises(ValidationError):
        AgentRuntimeConfig(max_synthesis_payload_bytes=value)


def test_budget_stops_initial_and_repair_requests_without_dropping_evidence(fiscal_context):
    class Builder:
        def build(self, **kwargs):
            return fiscal_context

    registry = create_skill_registry(Builder())
    request = ResearchAgentRequest(
        question="Research NVDA", ticker="NVDA", as_of_date=date(2025, 5, 25)
    )
    result = registry.get("equity_research").run(
        ticker=request.ticker, as_of_date=request.as_of_date
    )
    projection = project_evidence(result)
    before = projection.model_dump_json()
    payload, _ = synthesis_payload(
        question=request.question, projection=projection, response_language=ResponseLanguage.ENGLISH
    )
    size = len(payload.encode())
    client = FakeLLMClient([json.dumps(plan()), synthesis])
    with pytest.raises(PayloadBudgetExceeded) as failure:
        ResearchAgent(
            registry=registry,
            llm=client,
            config=AgentRuntimeConfig(max_synthesis_payload_bytes=size - 1),
        ).run(request)
    assert client.call_count == 1
    assert failure.value.actual_bytes == size
    assert len(failure.value.llm_usage) == 1
    assert projection.model_dump_json() == before
    allowed = FakeLLMClient([json.dumps(plan()), synthesis])
    assert (
        ResearchAgent(
            registry=registry,
            llm=allowed,
            config=AgentRuntimeConfig(max_synthesis_payload_bytes=size),
        )
        .run(request)
        .claims
    )
    assert allowed.call_count == 2
    repair = FakeLLMClient([json.dumps(plan()), "{malformed", synthesis])
    with pytest.raises(PayloadBudgetExceeded):
        ResearchAgent(
            registry=registry,
            llm=repair,
            config=AgentRuntimeConfig(max_synthesis_payload_bytes=size),
        ).run(request)
    assert repair.call_count == 2  # The larger repair envelope is never sent.
