from fastapi.testclient import TestClient

from financial_research.agent.config import AgentRuntimeConfig
from financial_research.agent.service import ResearchAgent
from financial_research.api.app import create_app
from financial_research.evals.dataset import DEFAULT_ROOT, load_suite
from financial_research.evals.fixtures import fixture_registry, load_fixtures
from financial_research.evals.offline import offline_agent_client


def test_legacy_requests_and_explicit_chinese_api_are_compatible():
    case = next(c for c in load_suite()[0].cases if c.case_id == "routing-fundamental_focus-en")
    fixture = load_fixtures(DEFAULT_ROOT)[case.fixture_scenario]

    def factory():
        return ResearchAgent(registry=fixture_registry(fixture), llm=offline_agent_client(case))

    body = {"question": case.question, "ticker": case.ticker, "as_of_date": str(case.as_of_date)}
    with TestClient(create_app(agent_factory=factory)) as client:
        legacy = client.post("/v1/agent/research", json=body)
        chinese = client.post("/v1/agent/research", json={**body, "response_language": "CHINESE"})
        invalid = client.post("/v1/agent/research", json={**body, "response_language": "FRENCH"})
    assert legacy.status_code == chinese.status_code == 200
    assert invalid.status_code == 422
    a, b = legacy.json()["data"], chinese.json()["data"]
    assert a["response_language"] == "ENGLISH" and b["response_language"] == "CHINESE"
    assert "研究摘要" in b["rendered_answer"]
    assert (
        a["citations"] == b["citations"]
        and a["calculation_provenance"] == b["calculation_provenance"]
    )


def test_payload_budget_error_has_sanitized_api_mapping_and_zero_synthesis_calls():
    case = load_suite()[0].cases[0]
    fixture = load_fixtures(DEFAULT_ROOT)[case.fixture_scenario]
    llm = offline_agent_client(case)
    agent = ResearchAgent(
        registry=fixture_registry(fixture),
        llm=llm,
        config=AgentRuntimeConfig(max_synthesis_payload_bytes=1),
    )
    with TestClient(create_app(agent_factory=lambda: agent)) as client:
        response = client.post(
            "/v1/agent/research",
            json={
                "question": case.question,
                "ticker": case.ticker,
                "as_of_date": str(case.as_of_date),
            },
        )
    assert response.status_code == 503
    assert response.json()["error_code"] == "SYNTHESIS_PAYLOAD_BUDGET_EXCEEDED"
    assert "evidence_index" not in response.text and "Traceback" not in response.text
    assert llm.call_count == 1
