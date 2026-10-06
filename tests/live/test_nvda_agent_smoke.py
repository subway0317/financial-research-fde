import os
from datetime import date

import pytest

from financial_research.agent.smoke import AgentSmokeStatus, run_live_agent_smoke
from financial_research.schemas.agent import ResearchAgentRequest


@pytest.mark.live
def test_nvda_agent_smoke():
    result = run_live_agent_smoke(
        request=ResearchAgentRequest(
            question="How have NVDA's fundamentals changed?",
            ticker="NVDA",
            as_of_date=date.fromisoformat(os.environ.get("LIVE_AS_OF_DATE", "2026-06-30")),
        )
    )
    assert result.status == AgentSmokeStatus.PASS, result.model_dump_json()
    assert result.selected_skill_id == "fundamental_analysis"
    assert result.llm_call_count <= 4
    if result.synthesis_readiness == "NOT_READY":
        assert result.agent_status == "BLOCKED"
        assert result.claim_count == 0
    else:
        assert result.claim_count > 0
