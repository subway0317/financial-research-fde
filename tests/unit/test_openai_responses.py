import json
from datetime import date

import httpx
import pytest

from financial_research.agent import smoke
from financial_research.agent.evidence_projection import project_evidence
from financial_research.agent.prompts import SYNTHESIS_PROMPT, SYNTHESIS_PROMPT_VERSION
from financial_research.agent.synthesis_payload import synthesis_payload
from financial_research.llm import openai_responses
from financial_research.llm.base import LLMRequest
from financial_research.llm.errors import (
    AgentConfigurationError,
    LLMProviderError,
    LLMStructuredOutputError,
)
from financial_research.llm.openai_responses import OpenAIConfig, OpenAIResponsesClient
from financial_research.schemas.agent import AgentPlan, ResearchAgentRequest, SynthesisOutput
from financial_research.skills.defaults import create_skill_registry

PLAN = {
    "plan_version": "1.0",
    "intent": "BROAD_RESEARCH",
    "selected_skill_id": "equity_research",
    "reason_code": "BROAD_EQUITY_RESEARCH_REQUEST",
    "ticker": "NVDA",
    "as_of_date": "2025-05-25",
    "requested_focus": None,
}
REQUEST = LLMRequest(
    phase="PLANNING",
    prompt_version="stage4-planner-v1",
    system_prompt="Contract only.",
    user_payload='{"question":"Research NVDA"}',
    repair_count=0,
)


def response_body(content, *, status="completed", usage=True):
    return {
        "id": "resp_offline",
        "object": "response",
        "created_at": 1,
        "model": "fixture-model",
        "status": status,
        "output": [
            {
                "id": "msg_offline",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": content,
            }
        ],
        "parallel_tool_calls": False,
        "tool_choice": "none",
        "tools": [],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 20,
            "total_tokens": 30,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        }
        if usage
        else None,
    }


@pytest.fixture
def configured(monkeypatch):
    # Deliberately non-secret placeholder, used exclusively with MockTransport.
    monkeypatch.setenv("OPENAI_API_KEY", "offline-placeholder")
    monkeypatch.setenv("OPENAI_MODEL", "fixture-model")
    monkeypatch.delenv("OPENAI_TIMEOUT_SECONDS", raising=False)


def test_default_timeout_configuration(configured):
    assert OpenAIConfig(model="fixture-model").timeout_seconds == 120
    assert OpenAIConfig.from_env().timeout_seconds == 120


def test_timeout_environment_override(configured, monkeypatch):
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "180.5")
    assert OpenAIConfig.from_env().timeout_seconds == 180.5


@pytest.mark.parametrize(
    "invalid", ["", " ", "0", "-1", "nan", "inf", "-inf", "1e999", "true", "private-invalid-value"]
)
def test_invalid_timeout_is_safe_configuration_error_before_sdk(configured, monkeypatch, invalid):
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", invalid)

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid configuration must not construct the SDK client")

    monkeypatch.setattr(openai_responses, "OpenAI", forbidden)
    with pytest.raises(
        AgentConfigurationError, match="OPENAI_TIMEOUT_SECONDS.*positive, finite"
    ) as failure:
        OpenAIResponsesClient()
    assert "private-invalid-value" not in str(failure.value)


@pytest.mark.parametrize("override,expected", [(None, 120), ("180.5", 180.5)])
def test_actual_sdk_receives_configured_timeout(configured, monkeypatch, override, expected):
    if override is not None:
        monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", override)
    calls = []

    def handler(request):
        calls.append(request.extensions["timeout"])
        return httpx.Response(
            200,
            json=response_body(
                [{"type": "output_text", "text": json.dumps(PLAN), "annotations": []}]
            ),
        )

    with OpenAIResponsesClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    ) as adapter:
        adapter.generate(REQUEST, AgentPlan)
    assert calls == [{"connect": expected, "read": expected, "write": expected, "pool": expected}]


@pytest.mark.parametrize("missing", ["OPENAI_API_KEY", "OPENAI_MODEL"])
def test_missing_configuration_fails_before_sdk_or_network(monkeypatch, missing):
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(AgentConfigurationError):
        OpenAIResponsesClient()


@pytest.mark.parametrize("has_usage", [True, False])
def test_actual_sdk_parse_sends_strict_stateless_schema_and_records_usage(configured, has_usage):
    calls = []

    def handler(request):
        assert request.url == "https://api.openai.com/v1/responses"
        body = json.loads(request.content)
        calls.append(body)
        assert body["model"] == "fixture-model"
        assert body["store"] is False
        assert body["text"]["format"]["type"] == "json_schema"
        assert body["text"]["format"]["strict"] is True
        schema = body["text"]["format"]["schema"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(PLAN)
        assert body["max_output_tokens"] == 8192
        for forbidden in ("previous_response_id", "conversation", "tools", "reasoning"):
            assert forbidden not in body or body[forbidden] == []
        return httpx.Response(
            200,
            json=response_body(
                [{"type": "output_text", "text": json.dumps(PLAN), "annotations": []}],
                usage=has_usage,
            ),
        )

    with OpenAIResponsesClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    ) as adapter:
        result = adapter.generate(REQUEST, AgentPlan)
    assert AgentPlan.model_validate_json(result.content).selected_skill_id == "equity_research"
    assert len(calls) == 1
    assert result.usage.input_tokens == (10 if has_usage else None)
    assert result.usage.output_tokens == (20 if has_usage else None)
    assert result.usage.total_tokens == (30 if has_usage else None)
    assert result.usage.provider == "openai"
    assert result.usage.latency_ms >= 0


def test_actual_sdk_sends_compact_synthesis_and_small_unchanged_output_schema(
    configured, fiscal_context
):
    class Builder:
        def build(self, **kwargs):
            return fiscal_context

    result = (
        create_skill_registry(Builder())
        .get("fundamental_analysis")
        .run(ticker="NVDA", as_of_date=date(2025, 5, 25))
    )
    projection = project_evidence(result)
    payload, audit = synthesis_payload(question="Research fundamentals", projection=projection)
    request = LLMRequest(
        phase="SYNTHESIS",
        prompt_version=SYNTHESIS_PROMPT_VERSION,
        system_prompt=SYNTHESIS_PROMPT,
        user_payload=payload,
        repair_count=0,
    )
    output = {
        "used_skill_ids": [projection.skill_id],
        "claims": [
            {
                "claim_id": "c1",
                "section": "FUNDAMENTALS",
                "claim_type": "INTERPRETATION",
                "statement": "Supplied fundamental evidence is available.",
                "evidence_ids": [next(iter(projection.evidence_index))],
            }
        ],
    }
    calls = []

    def handler(http_request):
        body = json.loads(http_request.content)
        calls.append(body)
        assert body["input"] == [
            {"role": "system", "content": SYNTHESIS_PROMPT},
            {"role": "user", "content": payload},
        ]
        assert len(body["input"][1]["content"].encode("utf-8")) == audit.request_bytes
        assert body["store"] is False
        format_spec = body["text"]["format"]
        assert format_spec["type"] == "json_schema"
        assert format_spec["strict"] is True
        assert set(format_spec["schema"]["required"]) == {"claims", "used_skill_ids"}
        assert len(json.dumps(format_spec, sort_keys=True, separators=(",", ":"))) < 1600
        assert "EvidenceReference" not in json.dumps(format_spec)
        return httpx.Response(
            200,
            json=response_body(
                [{"type": "output_text", "text": json.dumps(output), "annotations": []}]
            ),
        )

    with OpenAIResponsesClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    ) as adapter:
        response = adapter.generate(request, SynthesisOutput)
    assert len(calls) == 1
    assert SynthesisOutput.model_validate_json(response.content).model_dump(mode="json") == output


@pytest.mark.parametrize("failure", ["500", "429", "transport", "timeout"])
def test_actual_sdk_has_zero_hidden_retries_and_safe_failures(configured, failure, caplog):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if failure == "transport":
            raise httpx.ConnectError("private-provider-diagnostic", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("private-provider-diagnostic", request=request)
        return httpx.Response(
            int(failure), json={"error": {"message": "private-provider-diagnostic"}}
        )

    with OpenAIResponsesClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    ) as adapter:
        with pytest.raises(LLMProviderError) as error:
            adapter.generate(REQUEST, AgentPlan)
    assert calls == ["/v1/responses"]
    assert "private-provider-diagnostic" not in str(error.value)
    assert error.value.usage.success is False
    assert error.value.usage.input_tokens is None
    assert "private-provider-diagnostic" not in caplog.text
    if failure == "timeout":
        assert "exception_type=APITimeoutError" in caplog.text
        assert "http_status=None" in caplog.text
    elif failure in {"429", "500"}:
        assert error.value.http_status == int(failure)


def test_malformed_output_is_repairable_and_no_diagnostics_exposed(configured):
    def handler(request):
        return httpx.Response(
            200,
            json=response_body([{"type": "output_text", "text": "{malformed", "annotations": []}]),
        )

    with OpenAIResponsesClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    ) as adapter:
        with pytest.raises(LLMStructuredOutputError) as error:
            adapter.generate(REQUEST, AgentPlan)
    assert "malformed" not in str(error.value)
    # SDK parsing failed before returning a parsed response: usage is genuinely unavailable.
    assert error.value.usage.input_tokens is None


@pytest.mark.parametrize("failure", ["refusal", "incomplete"])
def test_refusal_and_incomplete_are_provider_failures(configured, failure):
    content = (
        [{"type": "refusal", "refusal": "private-refusal-text"}]
        if failure == "refusal"
        else [{"type": "output_text", "text": json.dumps(PLAN), "annotations": []}]
    )

    def handler(request):
        return httpx.Response(
            200,
            json=response_body(
                content, status="completed" if failure == "refusal" else "incomplete"
            ),
        )

    with OpenAIResponsesClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    ) as adapter:
        with pytest.raises(LLMProviderError) as error:
            adapter.generate(REQUEST, AgentPlan)
    assert "private-refusal-text" not in str(error.value)
    assert error.value.usage.total_tokens == 30


def test_synthesis_timeout_keeps_external_block_classification_and_two_calls(
    configured,
    monkeypatch,
    fiscal_context,
    caplog,
):
    monkeypatch.setenv("SEC_USER_AGENT", "offline-placeholder")

    class Builder:
        calls = 0

        def build(self, *, ticker, as_of_date):
            self.calls += 1
            assert (ticker, as_of_date) == ("NVDA", date(2025, 5, 25))
            return fiscal_context

    builder = Builder()
    registry = create_skill_registry(builder)
    monkeypatch.setattr(smoke, "create_skill_registry", lambda: registry)
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if len(calls) == 2:
            raise httpx.ReadTimeout("private-timeout-diagnostic", request=request)
        plan = {
            **PLAN,
            "intent": "FUNDAMENTAL_FOCUS",
            "selected_skill_id": "fundamental_analysis",
            "reason_code": "FUNDAMENTAL_ANALYSIS_REQUEST",
        }
        return httpx.Response(
            200,
            json=response_body(
                [{"type": "output_text", "text": json.dumps(plan), "annotations": []}]
            ),
        )

    def adapter():
        return OpenAIResponsesClient(
            http_client=httpx.Client(transport=httpx.MockTransport(handler))
        )

    monkeypatch.setattr(smoke, "OpenAIResponsesClient", adapter)
    result = smoke.run_live_agent_smoke(
        request=ResearchAgentRequest(
            question="How have NVDA's fundamentals changed?",
            ticker="NVDA",
            as_of_date=date(2025, 5, 25),
        )
    )
    assert result.status == smoke.AgentSmokeStatus.EXTERNAL_BLOCKED
    assert result.error_code == "LLM_PROVIDER_ERROR"
    assert result.llm_call_count == 2
    assert calls == ["/v1/responses", "/v1/responses"]
    assert builder.calls == 1
    assert [usage.phase for usage in result.llm_usage] == ["PLANNING", "SYNTHESIS"]
    assert result.llm_usage[-1].input_tokens is None
    assert result.llm_usage[-1].repair_count == 0
    assert "phase=SYNTHESIS exception_type=APITimeoutError http_status=None" in caplog.text
    assert "private-timeout-diagnostic" not in caplog.text + result.model_dump_json()


def test_frozen_case_runs_planner_synthesis_and_judge_through_actual_sdk_without_sec(
    configured, monkeypatch
):
    from financial_research.agent.config import AgentRuntimeConfig
    from financial_research.evals.dataset import DEFAULT_ROOT, load_suite
    from financial_research.evals.fixtures import load_fixtures
    from financial_research.evals.judge import ClaimSupportJudge
    from financial_research.evals.offline import scripted_judgment, scripted_synthesis
    from financial_research.evals.runner import evaluate_case

    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    case = next(c for c in load_suite()[0].cases if c.case_id == "routing-fundamental_focus-en")
    plan = {
        **PLAN,
        "intent": "FUNDAMENTAL_FOCUS",
        "selected_skill_id": "fundamental_analysis",
        "reason_code": "FUNDAMENTAL_ANALYSIS_REQUEST",
    }
    calls = []

    def handler(http_request):
        body = json.loads(http_request.content)
        name = body["text"]["format"]["name"]
        calls.append(name)
        assert body["store"] is False and body["text"]["format"]["strict"] is True
        assert http_request.url.host == "api.openai.com"
        phase = "SEMANTIC_JUDGE" if name == "JudgeOutput" else "SYNTHESIS"
        request = LLMRequest(
            phase=phase,
            prompt_version="offline-http-test",
            system_prompt=body["input"][0]["content"],
            user_payload=body["input"][1]["content"],
            repair_count=0,
        )
        text = (
            json.dumps(plan)
            if name == "AgentPlan"
            else scripted_synthesis(request)
            if name == "SynthesisOutput"
            else scripted_judgment(request)
        )
        return httpx.Response(
            200, json=response_body([{"type": "output_text", "text": text, "annotations": []}])
        )

    with OpenAIResponsesClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    ) as adapter:
        result = evaluate_case(
            case,
            load_fixtures(DEFAULT_ROOT)[case.fixture_scenario],
            adapter,
            ClaimSupportJudge(adapter),
            AgentRuntimeConfig(),
        )
    assert calls == ["AgentPlan", "SynthesisOutput", "JudgeOutput"]
    assert result.status == "COMPLETED"
    assert result.claim_evaluations[0].verdict == "SUPPORTED"
    assert result.judge_usage[0].phase == "SEMANTIC_JUDGE"
    assert result.judge_usage[0].input_tokens == 10
