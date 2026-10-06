"""Official Responses structured outputs. Stateless, credential-safe and no SDK retries."""

import logging
import os
import time
from types import TracebackType
from typing import Self

import httpx
from openai import APIError, APIStatusError, OpenAI
from pydantic import BaseModel, Field, ValidationError

from financial_research.llm.base import LLMRequest, LLMResponse
from financial_research.llm.errors import (
    AgentConfigurationError,
    LLMProviderError,
    LLMStructuredOutputError,
)
from financial_research.schemas.agent import LLMUsageMetadata
from financial_research.schemas.base import CanonicalModel, NonEmpty

logger = logging.getLogger(__name__)


class OpenAIConfig(CanonicalModel):
    model: NonEmpty
    timeout_seconds: float = Field(default=120.0, gt=0, allow_inf_nan=False)
    max_output_tokens: int = Field(default=8192, ge=256, le=16384)

    @classmethod
    def from_env(cls) -> Self:
        if not os.environ.get("OPENAI_API_KEY") or not os.environ.get("OPENAI_MODEL"):
            raise AgentConfigurationError("OPENAI_API_KEY and OPENAI_MODEL are required.")
        values = {"model": os.environ["OPENAI_MODEL"]}
        timeout = os.environ.get("OPENAI_TIMEOUT_SECONDS")
        if timeout is not None:
            values["timeout_seconds"] = timeout
        try:
            return cls.model_validate(values)
        except ValidationError as exc:
            if any(
                error["loc"] == ("timeout_seconds",) for error in exc.errors(include_input=False)
            ):
                raise AgentConfigurationError(
                    "OPENAI_TIMEOUT_SECONDS must be a positive, finite number of seconds."
                ) from None
            raise AgentConfigurationError("OpenAI model configuration is invalid.") from None


class OpenAIResponsesClient:
    provider = "openai"

    def __init__(
        self,
        config: OpenAIConfig | None = None,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._config = config or OpenAIConfig.from_env()
        if not os.environ.get("OPENAI_API_KEY"):
            raise AgentConfigurationError("OPENAI_API_KEY is required.")
        self.model = self._config.model
        self._client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url="https://api.openai.com/v1",
            max_retries=0,
            timeout=self._config.timeout_seconds,
            http_client=http_client,
        )

    def generate(self, request: LLMRequest, output_type: type[BaseModel]) -> LLMResponse:
        started = time.perf_counter()
        error: LLMProviderError
        try:
            response = self._client.responses.parse(
                model=self.model,
                store=False,
                text_format=output_type,
                max_output_tokens=self._config.max_output_tokens,
                input=[
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": request.user_payload},
                ],
            )
        except ValidationError:
            error = LLMStructuredOutputError("Structured response validation failed.")
            error.usage = self._usage(request, started, success=False)
            raise error from None
        except APIError as exc:
            error = LLMProviderError()
            error.http_status = exc.status_code if isinstance(exc, APIStatusError) else None
            error.usage = self._usage(request, started, success=False)
            logger.warning(
                "OpenAI request failed phase=%s exception_type=%s http_status=%s",
                request.phase,
                type(exc).__name__,
                error.http_status,
            )
            raise error from None
        reported = response.usage
        usage = self._usage(request, started, success=True).model_copy(
            update={
                "model": response.model,
                "input_tokens": reported.input_tokens if reported else None,
                "output_tokens": reported.output_tokens if reported else None,
                "total_tokens": reported.total_tokens if reported else None,
            }
        )
        if response.status != "completed" or response.output_parsed is None:
            error = LLMProviderError("LLM refused or did not complete structured output.")
            error.usage = usage.model_copy(update={"success": False})
            raise error
        try:
            parsed = output_type.model_validate(response.output_parsed.model_dump())
        except ValidationError:
            error = LLMStructuredOutputError("Structured response validation failed.")
            error.usage = usage.model_copy(update={"success": False})
            raise error from None
        return LLMResponse(content=parsed.model_dump_json(), usage=usage)

    def _usage(self, request: LLMRequest, started: float, *, success: bool) -> LLMUsageMetadata:
        return LLMUsageMetadata(
            provider=self.provider,
            model=self.model,
            phase=request.phase,
            prompt_version=request.prompt_version,
            latency_ms=(time.perf_counter() - started) * 1000,
            repair_count=request.repair_count,
            success=success,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
