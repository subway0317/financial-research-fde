import json
from datetime import date
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from financial_research.agent.errors import (
    AgentIntegrityError,
    AgentPlanValidationError,
    GroundingValidationError,
)
from financial_research.agent.service import ResearchAgent
from financial_research.api.app import create_app
from financial_research.llm.errors import AgentConfigurationError, LLMProviderError
from financial_research.llm.fake import FakeLLMClient
from financial_research.schemas.agent import GroundedResearchAnswer
from financial_research.skills.defaults import create_skill_registry
from financial_research.skills.errors import EvidenceIntegrityError

BODY = {
    "question": "How have NVDA fundamentals changed?",
    "ticker": "NVDA",
    "as_of_date": "2025-05-25",
}
PLAN = {
    "plan_version": "1.0",
    "intent": "FUNDAMENTAL_FOCUS",
    "selected_skill_id": "fundamental_analysis",
    "reason_code": "FUNDAMENTAL_ANALYSIS_REQUEST",
    "ticker": "NVDA",
    "as_of_date": "2025-05-25",
    "requested_focus": None,
}


def synthesis(request):
    payload = json.loads(request.user_payload)["projection"]
    key = next(iter(payload["evidence_index"]))
    return json.dumps(
        {
            "used_skill_ids": [payload["skill_id"]],
            "claims": [
                {
                    "claim_id": "c1",
                    "section": "FUNDAMENTALS",
                    "claim_type": "INTERPRETATION",
                    "statement": "Supplied fundamental evidence is available.",
                    "evidence_ids": [key],
                }
            ],
        }
    )


def make_agent(context):
    class Builder:
        def build(self, *, ticker, as_of_date):
            assert (ticker, as_of_date) == ("NVDA", date(2025, 5, 25))
            return context

    return ResearchAgent(
        registry=create_skill_registry(Builder()), llm=FakeLLMClient([json.dumps(PLAN), synthesis])
    )


def test_agent_success_envelope_and_stateless_request_ids(fiscal_context):
    with TestClient(create_app(agent_factory=lambda: make_agent(fiscal_context))) as client:
        first = client.post("/v1/agent/research", json=BODY)
        second = client.post("/v1/agent/research", json=BODY)
    assert first.status_code == second.status_code == 200
    data = first.json()
    assert data["request_id"] == first.headers["X-Request-ID"]
    assert UUID(data["request_id"]).version == 4
    assert data["request_id"] != second.json()["request_id"]
    assert data["schema_version"] == "1.0"
    assert data["quality"] == data["data"]["quality"]
    assert data["limitations"] == data["data"]["limitations"]
    answer = GroundedResearchAnswer.model_validate(data["data"])
    assert answer.agent_status == "COMPLETED_WITH_WARNINGS"
    assert answer.used_skill_ids == ("fundamental_analysis",)
    assert answer.claims and answer.rendered_answer and answer.citations
    assert len(answer.llm_usage) == 2
    for forbidden in ("system_prompt", "user_payload", "raw-provider", "Traceback", "reasoning"):
        assert forbidden not in first.text


def test_blocked_is_http_200_and_has_no_synthesis(nvda_context):
    # Existing fixture lacks legal fiscal comparison pairs: domain UNAVAILABLE.
    agent = make_agent(nvda_context)
    with TestClient(create_app(agent_factory=lambda: agent)) as client:
        response = client.post("/v1/agent/research", json=BODY)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["agent_status"] == "BLOCKED"
    assert data["synthesis_readiness"] == "NOT_READY"
    assert data["claims"] == []
    assert len(data["llm_usage"]) == 1


@pytest.mark.parametrize(
    "error,status,code",
    [
        (AgentConfigurationError, 503, "AGENT_CONFIGURATION_ERROR"),
        (LLMProviderError, 502, "LLM_PROVIDER_ERROR"),
        (AgentPlanValidationError, 500, "AGENT_PLAN_VALIDATION_ERROR"),
        (GroundingValidationError, 500, "GROUNDING_VALIDATION_ERROR"),
        (AgentIntegrityError, 500, "AGENT_INTEGRITY_ERROR"),
        (EvidenceIntegrityError, 500, "EVIDENCE_INTEGRITY_ERROR"),
    ],
)
def test_agent_error_mapping_and_sanitization(error, status, code):
    def broken():
        raise error("private-secret /tmp/private-path raw-provider-message")

    with TestClient(create_app(agent_factory=broken), raise_server_exceptions=False) as client:
        response = client.post("/v1/agent/research", json=BODY)
    assert response.status_code == status
    assert response.json()["error_code"] == code
    assert response.headers["X-Request-ID"] == response.json()["request_id"]
    assert all(
        secret not in response.text
        for secret in ("private-secret", "/tmp/", "raw-provider", "Traceback")
    )


def test_default_agent_missing_env_is_503_and_health_docs_stay_independent(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/docs").status_code == 200
        schema = client.get("/openapi.json").json()
        response = client.post("/v1/agent/research", json=BODY)
    assert response.status_code == 503
    assert response.json()["error_code"] == "AGENT_CONFIGURATION_ERROR"
    assert len(schema["paths"]) == 8
    assert "/v1/agent/research" in schema["paths"]
    assert schema["paths"]["/v1/agent/research"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/AgentResearchRequest"}
    assert (
        schema["components"]["schemas"]["GroundedClaim"]["properties"]["evidence_ids"]["minItems"]
        == 1
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"question": " "},
        {"question": "x" * 8001},
        {"as_of_date": "2025-05-25T00:00:00Z"},
        {"ticker": ["NVDA", "AAPL"]},
        {"conversation_history": []},
    ],
)
def test_agent_request_validation(updates, fiscal_context):
    with TestClient(create_app(agent_factory=lambda: make_agent(fiscal_context))) as client:
        response = client.post("/v1/agent/research", json={**BODY, **updates})
    assert response.status_code == 422
    assert response.json()["error_code"] == "REQUEST_VALIDATION_ERROR"


def test_default_agent_validates_input_before_missing_config(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with TestClient(create_app()) as client:
        response = client.post("/v1/agent/research", json={**BODY, "question": " "})
    assert response.status_code == 422
    assert response.json()["error_code"] == "REQUEST_VALIDATION_ERROR"


@pytest.mark.parametrize(
    "phase,status,code",
    [
        ("planner", 500, "AGENT_PLAN_VALIDATION_ERROR"),
        ("grounding", 500, "GROUNDING_VALIDATION_ERROR"),
        ("provider", 502, "LLM_PROVIDER_ERROR"),
    ],
)
def test_api_maps_actual_agent_failures_after_bounded_execution(
    fiscal_context, phase, status, code
):
    class Builder:
        def build(self, **kwargs):
            return fiscal_context

    if phase == "planner":
        replies = ["broken", "broken"]
    elif phase == "grounding":
        replies = [json.dumps(PLAN), "broken", "broken"]
    else:
        replies = [json.dumps(PLAN), LLMProviderError("private-diagnostic")]
    llm = FakeLLMClient(replies)
    agent = ResearchAgent(registry=create_skill_registry(Builder()), llm=llm)
    with TestClient(
        create_app(agent_factory=lambda: agent), raise_server_exceptions=False
    ) as client:
        response = client.post("/v1/agent/research", json=BODY)
    assert response.status_code == status
    assert response.json()["error_code"] == code
    assert llm.call_count == (3 if phase == "grounding" else 2)
    assert "private-diagnostic" not in response.text
