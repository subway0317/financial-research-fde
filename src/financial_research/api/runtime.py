"""Live transport composition shared by API/CLI; imports make no external requests."""

from collections.abc import Iterator
from contextlib import contextmanager

from financial_research.agent.service import ResearchAgent
from financial_research.config import ResearchConfig
from financial_research.llm.openai_responses import OpenAIResponsesClient
from financial_research.research.live import LiveContextBuilder
from financial_research.skills.defaults import create_skill_registry


@contextmanager
def live_agent(config: ResearchConfig | None = None) -> Iterator[ResearchAgent]:
    with OpenAIResponsesClient() as client:
        yield ResearchAgent(registry=create_skill_registry(LiveContextBuilder(config)), llm=client)
