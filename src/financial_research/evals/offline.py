"""Scripted contracts with known synthetic support; scores do not measure real models."""

import json

from financial_research.agent.planner import INTENT_REASONS, INTENT_SKILLS
from financial_research.evals.schemas import AgentEvalCase
from financial_research.llm.base import LLMRequest
from financial_research.llm.fake import FakeLLMClient
from financial_research.schemas.agent import AgentIntent


def scripted_synthesis(request: LLMRequest) -> str:
    data = json.loads(request.user_payload)
    if "original_input" in data:
        data = data["original_input"]
    projection = data["projection"]
    key, reference = next(
        (key, ref)
        for key, ref in projection["evidence_index"].items()
        if ref["kind"] == "SOURCE_FACT"
    )
    period = reference.get("period_end", reference.get("date", "supplied period"))
    metric, value, unit = reference["metric"], reference.get("value"), reference.get("unit", "")
    statement = (
        f"所提供的 {metric} 在 {period} 的数值为 {value} {unit}。"
        if data.get("response_language") == "CHINESE"
        else f"The supplied {metric} value for {period} is {value} {unit}."
    )
    return json.dumps(
        {
            "used_skill_ids": [projection["skill_id"]],
            "claims": [
                {
                    "claim_id": "c1",
                    "section": "FUNDAMENTALS",
                    "claim_type": "SOURCE_FACT",
                    "statement": statement,
                    "evidence_ids": [key],
                }
            ],
        }
    )


def offline_agent_client(case: AgentEvalCase) -> FakeLLMClient:
    intent = case.expected_intent or AgentIntent.BROAD_RESEARCH
    plan = {
        "plan_version": "1.0",
        "intent": intent,
        "selected_skill_id": INTENT_SKILLS[intent],
        "reason_code": INTENT_REASONS[intent],
        "ticker": case.ticker,
        "as_of_date": case.as_of_date.isoformat(),
        "requested_focus": None,
    }
    return FakeLLMClient([json.dumps(plan), scripted_synthesis])


def scripted_judgment(request: LLMRequest) -> str:
    # Labels apply to the fixed source-value claims above, not a semantic inference engine.
    claims = json.loads(request.user_payload)["claims"]
    return json.dumps(
        {
            "evaluations": [
                {
                    "claim_id": c["claim_id"],
                    "verdict": "SUPPORTED",
                    "severity": "LOW",
                    "reason_code": "DIRECT_EVIDENCE_SUPPORT",
                    "evidence_ids": c["evidence_ids"],
                }
                for c in claims
            ]
        }
    )


def offline_judge_client() -> FakeLLMClient:
    return FakeLLMClient([scripted_judgment])
