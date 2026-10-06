"""Opt-in CLI composition of the official LLM adapter and registered live Skills."""

import argparse
import os
import sys
from datetime import date
from enum import StrEnum

from financial_research.agent.errors import AgentIntegrityError
from financial_research.agent.service import ResearchAgent
from financial_research.exceptions import ProviderError, UnknownTickerError
from financial_research.llm.errors import AgentConfigurationError, LLMProviderError
from financial_research.llm.openai_responses import OpenAIResponsesClient
from financial_research.schemas.agent import (
    AgentIntent,
    AgentStatus,
    LLMUsageMetadata,
    ResearchAgentRequest,
    SynthesisPayloadAudit,
)
from financial_research.schemas.base import CanonicalModel
from financial_research.schemas.skills import SynthesisReadiness
from financial_research.skills.defaults import create_skill_registry


class AgentSmokeStatus(StrEnum):
    PASS = "PASS"
    USER_CONFIGURATION_REQUIRED = "USER_CONFIGURATION_REQUIRED"
    EXTERNAL_BLOCKED = "EXTERNAL_BLOCKED"
    FAIL = "FAIL"


class AgentSmokeResult(CanonicalModel):
    status: AgentSmokeStatus
    ticker: str
    as_of_date: date
    missing_configuration: tuple[str, ...] = ()
    selected_skill_id: str | None = None
    agent_status: AgentStatus | None = None
    synthesis_readiness: SynthesisReadiness | None = None
    claim_count: int = 0
    evidence_count: int = 0
    llm_call_count: int = 0
    llm_usage: tuple[LLMUsageMetadata, ...] = ()
    synthesis_payload_audit: SynthesisPayloadAudit | None = None
    limitations: tuple[str, ...] = ()
    error_code: str | None = None


def run_live_agent_smoke(*, request: ResearchAgentRequest) -> AgentSmokeResult:
    missing = tuple(
        name
        for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "SEC_USER_AGENT")
        if not os.environ.get(name)
    )
    if missing:
        return AgentSmokeResult(
            status=AgentSmokeStatus.USER_CONFIGURATION_REQUIRED,
            ticker=request.ticker,
            as_of_date=request.as_of_date,
            missing_configuration=missing,
        )
    registry = create_skill_registry()
    try:
        with OpenAIResponsesClient() as client:
            answer = ResearchAgent(registry=registry, llm=client).run(request)
        # The smoke question is deliberately fixed to a single fundamental focus.
        if (
            answer.plan.intent != AgentIntent.FUNDAMENTAL_FOCUS
            or answer.used_skill_ids != ("fundamental_analysis",)
            or answer.plan.selected_skill_id not in {entry.skill_id for entry in registry.list()}
            or len(answer.llm_usage) > 4
        ):
            raise AgentIntegrityError("SMOKE_ROUTING_INTEGRITY")
        return AgentSmokeResult(
            status=AgentSmokeStatus.PASS,
            ticker=request.ticker,
            as_of_date=request.as_of_date,
            selected_skill_id=answer.plan.selected_skill_id,
            agent_status=answer.agent_status,
            synthesis_readiness=answer.synthesis_readiness,
            claim_count=len(answer.claims),
            evidence_count=len(answer.citations),
            llm_call_count=len(answer.llm_usage),
            llm_usage=answer.llm_usage,
            synthesis_payload_audit=answer.synthesis_payload_audit,
            limitations=answer.limitations,
        )
    except AgentConfigurationError:
        return AgentSmokeResult(
            status=AgentSmokeStatus.USER_CONFIGURATION_REQUIRED,
            ticker=request.ticker,
            as_of_date=request.as_of_date,
            error_code="AGENT_CONFIGURATION_ERROR",
        )
    except LLMProviderError as exc:
        status = (
            AgentSmokeStatus.FAIL
            if exc.http_status in {400, 404, 422}
            else AgentSmokeStatus.EXTERNAL_BLOCKED
        )
        return AgentSmokeResult(
            status=status,
            ticker=request.ticker,
            as_of_date=request.as_of_date,
            error_code="LLM_PROVIDER_ERROR",
            llm_call_count=len(exc.llm_usage),
            llm_usage=exc.llm_usage,
        )
    except ProviderError:
        return AgentSmokeResult(
            status=AgentSmokeStatus.EXTERNAL_BLOCKED,
            ticker=request.ticker,
            as_of_date=request.as_of_date,
            error_code="EXTERNAL_PROVIDER_ERROR",
        )
    except (AgentIntegrityError, UnknownTickerError):
        return AgentSmokeResult(
            status=AgentSmokeStatus.FAIL,
            ticker=request.ticker,
            as_of_date=request.as_of_date,
            error_code="AGENT_INTEGRITY_ERROR",
        )
    except Exception:
        return AgentSmokeResult(
            status=AgentSmokeStatus.FAIL,
            ticker=request.ticker,
            as_of_date=request.as_of_date,
            error_code="SMOKE_EXECUTION_FAILURE",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", default="NVDA")
    parser.add_argument("--as-of-date", required=True, type=date.fromisoformat)
    args = parser.parse_args()
    request = ResearchAgentRequest(
        question=f"How have {args.ticker}'s fundamentals changed?",
        ticker=args.ticker,
        as_of_date=args.as_of_date,
    )
    result = run_live_agent_smoke(request=request)
    sys.stdout.write(result.model_dump_json(indent=2) + "\n")
    codes = {
        AgentSmokeStatus.PASS: 0,
        AgentSmokeStatus.USER_CONFIGURATION_REQUIRED: 3,
        AgentSmokeStatus.EXTERNAL_BLOCKED: 2,
        AgentSmokeStatus.FAIL: 1,
    }
    sys.exit(codes[result.status])


if __name__ == "__main__":
    main()
