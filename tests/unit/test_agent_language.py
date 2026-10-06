import json

import pytest

from financial_research.agent.errors import GroundingValidationError
from financial_research.agent.language import resolve_language
from financial_research.agent.policy import validate_research_policy
from financial_research.agent.service import ResearchAgent
from financial_research.evals.dataset import DEFAULT_ROOT, load_suite
from financial_research.evals.fixtures import fixture_registry, load_fixtures
from financial_research.evals.offline import offline_agent_client
from financial_research.llm.fake import FakeLLMClient
from financial_research.schemas.agent import ResearchAgentRequest


@pytest.mark.parametrize(
    "question,override,expected,fallback",
    [
        ("How have NVDA's fundamentals changed?", "AUTO", "ENGLISH", False),
        ("分析 NVDA 营收和利润趋势。", "AUTO", "CHINESE", False),
        ("帮我 analyze NVDA fundamentals.", "AUTO", "CHINESE", False),
        ("NVDA revenue?", "AUTO", "ENGLISH", True),
        ("Analyze NVDA fundamentals", "CHINESE", "CHINESE", False),
        ("分析 NVDA 基本面", "ENGLISH", "ENGLISH", False),
    ],
)
def test_language_resolution_is_small_deterministic_and_explicit(
    question, override, expected, fallback
):
    case = load_suite()[0].cases[0]
    request = ResearchAgentRequest(
        question=question,
        ticker=case.ticker,
        as_of_date=case.as_of_date,
        response_language=override,
    )
    assert resolve_language(request) == (expected, fallback)


def test_multilingual_requests_keep_planning_input_and_financial_evidence_identical():
    suite, _ = load_suite()
    case = next(c for c in suite.cases if c.case_id == "routing-fundamental_focus-en")
    fixture = load_fixtures(DEFAULT_ROOT)[case.fixture_scenario]
    answers, clients = [], []
    for language in ("ENGLISH", "CHINESE"):
        client = offline_agent_client(case)
        answers.append(
            ResearchAgent(registry=fixture_registry(fixture), llm=client).run(
                ResearchAgentRequest(
                    question=case.question,
                    ticker=case.ticker,
                    as_of_date=case.as_of_date,
                    response_language=language,
                )
            )
        )
        clients.append(client)
    assert clients[0].requests[0].user_payload == clients[1].requests[0].user_payload
    first, second = answers
    assert first.plan == second.plan
    assert first.citations == second.citations
    assert first.calculation_provenance == second.calculation_provenance
    assert first.quality == second.quality
    assert first.limitations == second.limitations
    assert "Research Summary" in first.rendered_answer and "Key Findings" in first.rendered_answer
    for heading in ("研究摘要", "关键发现", "数据质量", "限制"):
        assert heading in second.rendered_answer
    assert all(key in second.rendered_answer for key in second.claims[0].evidence_ids)


def test_wrong_explicit_language_gets_only_one_bounded_repair():
    case = next(c for c in load_suite()[0].cases if c.case_id == "language-en-to-zh")
    fixture = load_fixtures(DEFAULT_ROOT)[case.fixture_scenario]
    normal = offline_agent_client(case)
    answer = ResearchAgent(registry=fixture_registry(fixture), llm=normal).run(
        ResearchAgentRequest(question=case.question, ticker=case.ticker, as_of_date=case.as_of_date)
    )
    bad = json.dumps(
        {
            "used_skill_ids": answer.used_skill_ids,
            "claims": [c.model_dump(mode="json") for c in answer.claims],
        }
    )
    client = FakeLLMClient([json.dumps(answer.plan.model_dump(mode="json")), bad, bad])
    with pytest.raises(GroundingValidationError, match="LANGUAGE_CONTRACT_VIOLATION"):
        ResearchAgent(registry=fixture_registry(fixture), llm=client).run(
            ResearchAgentRequest(
                question=case.question,
                ticker=case.ticker,
                as_of_date=case.as_of_date,
                response_language="CHINESE",
            )
        )
    assert client.call_count == 3


@pytest.mark.parametrize(
    "statement",
    [
        "Buy NVDA.",
        "Sell NVDA.",
        "My target price is $200.",
        "建议买入 NVDA。",
        "建议卖出 NVDA。",
        "NVDA 的目标价是 200 美元。",
        "我认为现在应该买入。",
    ],
)
def test_bilingual_obvious_recommendations_are_rejected(statement):
    with pytest.raises(GroundingValidationError, match="PROHIBITED_RECOMMENDATION"):
        validate_research_policy(statement)


@pytest.mark.parametrize(
    "statement",
    ["The company reported a share buyback.", "公司报告了股份回购。", "公司购买了设备。"],
)
def test_descriptive_business_actions_are_allowed(statement):
    validate_research_policy(statement)
