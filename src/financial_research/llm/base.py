"""A stateless structured-text interface; no tools or conversation handles."""

from typing import Protocol

from pydantic import BaseModel

from financial_research.schemas.agent import LLMPhase, LLMUsageMetadata
from financial_research.schemas.base import CanonicalModel, NonEmpty


class LLMRequest(CanonicalModel):
    phase: LLMPhase
    prompt_version: NonEmpty
    system_prompt: NonEmpty
    user_payload: NonEmpty
    repair_count: int


class LLMResponse(CanonicalModel):
    content: str
    usage: LLMUsageMetadata


class LLMClient(Protocol):
    @property
    def provider(self) -> str: ...
    @property
    def model(self) -> str: ...
    def generate(self, request: LLMRequest, output_type: type[BaseModel]) -> LLMResponse: ...
