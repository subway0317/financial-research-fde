"""Report tests run the real providers/core/Skills/Agent with offline transports."""

import json
from datetime import date

import pytest

from financial_research.agent.service import ResearchAgent
from financial_research.llm.fake import FakeLLMClient
from financial_research.reports.schemas import EquityResearchReportRequest
from financial_research.reports.service import ReportWorkflowService
from financial_research.skills.defaults import create_skill_registry

REQUEST = EquityResearchReportRequest(ticker="NVDA", as_of_date=date(2025, 5, 25))


def report_synthesis(request):
    payload = json.loads(request.user_payload)
    payload = payload.get("original_input", payload)
    projection = payload["projection"]
    chinese = payload["response_language"] == "CHINESE"
    source = next(
        key
        for key, ref in projection["evidence_index"].items()
        if ref["kind"] == "SOURCE_FACT" and ref["metric"] == "revenue"
    )
    computed = next(
        key
        for key, ref in projection["evidence_index"].items()
        if ref["kind"] == "COMPUTATION" and ref["metric"] == "revenue"
    )
    market = next(
        key for key, ref in projection["evidence_index"].items() if ref["metric"] == "close"
    )
    claims = [
        (
            "company",
            "COMPANY",
            "INTERPRETATION",
            "所提供的公司标识为 NVDA。" if chinese else "The supplied company identifier is NVDA.",
            source,
        ),
        (
            "revenue",
            "FUNDAMENTALS",
            "COMPUTED_FACT",
            "收入从 100 增加至 150。" if chinese else "Revenue increased from 100 to 150.",
            computed,
        ),
        (
            "market",
            "MARKET",
            "SOURCE_FACT",
            "所提供的收盘价为 " + projection["evidence_index"][market]["value"] + "。"
            if chinese
            else "The supplied close is " + projection["evidence_index"][market]["value"] + ".",
            market,
        ),
        (
            "quality",
            "QUALITY",
            "INTERPRETATION",
            "所提供的数据质量状态为 " + projection["quality"]["status"] + "。"
            if chinese
            else "The supplied quality status is " + projection["quality"]["status"] + ".",
            source,
        ),
    ]
    return json.dumps(
        {
            "used_skill_ids": [projection["skill_id"]],
            "claims": [
                {
                    "claim_id": key,
                    "section": section,
                    "claim_type": kind,
                    "statement": statement,
                    "evidence_ids": [evidence_id],
                }
                for key, section, kind, statement, evidence_id in claims
            ],
        }
    )


@pytest.fixture
def report_agent_factory(fiscal_context):
    def create(context=None, replies=None, config=None, builder_error=None):
        class Builder:
            calls = 0

            def build(self, *, ticker, as_of_date):
                self.calls += 1
                assert (ticker, as_of_date) == (REQUEST.ticker, REQUEST.as_of_date)
                if builder_error is not None:
                    raise builder_error
                return context if context is not None else fiscal_context

        class CapturingAgent(ResearchAgent):
            last_answer = None

            def execute_validated_plan(self, request, plan):
                answer = super().execute_validated_plan(request, plan)
                self.last_answer = answer
                return answer

        builder = Builder()
        llm = FakeLLMClient([report_synthesis] if replies is None else replies)
        agent = CapturingAgent(registry=create_skill_registry(builder), llm=llm, config=config)
        return agent, llm, builder

    return create


@pytest.fixture
def report_run(report_agent_factory):
    agent, llm, builder = report_agent_factory()
    response = ReportWorkflowService(agent).run(REQUEST)
    return response, agent.last_answer, llm, builder
