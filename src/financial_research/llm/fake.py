"""Scripted offline transport; recorded prompts are test-local, never API artifacts."""

from collections import deque
from collections.abc import Callable, Iterable

from pydantic import BaseModel

from financial_research.llm.base import LLMRequest, LLMResponse
from financial_research.schemas.agent import LLMUsageMetadata

type FakeReply = str | BaseModel | Exception | Callable[[LLMRequest], str | BaseModel]


class FakeLLMClient:
    provider = "fake"
    model = "scripted"

    def __init__(self, replies: Iterable[FakeReply]) -> None:
        self._replies = deque(replies)
        self.requests: list[LLMRequest] = []

    @property
    def call_count(self) -> int:
        return len(self.requests)

    def generate(self, request: LLMRequest, output_type: type[BaseModel]) -> LLMResponse:
        self.requests.append(request)
        if not self._replies:
            raise AssertionError("fake LLM script exhausted")
        reply = self._replies.popleft()
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            reply = reply(request)
        return LLMResponse(
            content=reply.model_dump_json() if isinstance(reply, BaseModel) else reply,
            usage=LLMUsageMetadata(
                provider="fake",
                model="scripted",
                phase=request.phase,
                prompt_version=request.prompt_version,
                latency_ms=0,
                repair_count=request.repair_count,
                success=True,
            ),
        )
