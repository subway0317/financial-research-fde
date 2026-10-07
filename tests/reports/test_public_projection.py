"""Offline disclosure accounting, reconstruction and internal audit regressions."""

import json
from collections import Counter

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from financial_research.agent.evidence_projection import project_evidence
from financial_research.agent.grounding import validate_grounding
from financial_research.agent.service import ResearchAgent
from financial_research.deployment.app import create_production_app
from financial_research.deployment.config import DeploymentConfig
from financial_research.llm.fake import FakeLLMClient
from financial_research.public_research.projection import (
    project_agent,
    project_references,
    project_report,
    project_tool_result,
)
from financial_research.public_research.schemas import (
    PublicEvidenceReference,
    PublicResearchReport,
)
from financial_research.reports.bundle import export_bundle
from financial_research.reports.schemas import EquityResearchReportRequest
from financial_research.reports.service import REPORT_TASK_V1, ReportWorkflowService
from financial_research.reports.validation import ReportBundleValidator
from financial_research.schemas.agent import SynthesisOutput
from financial_research.schemas.tools import EvidenceReference
from financial_research.tools import ResearchTools

from .test_tiingo_payload import AS_OF, cite_all_calculations, offline_context, registry_for


def daily_sources(payload):
    """Independent extraction of disclosed daily source values, including nested records."""
    if isinstance(payload, dict):
        if (
            payload.get("kind") == "SOURCE_FACT"
            and payload.get("date")
            and payload.get("value") is not None
        ):
            yield payload
        for item in payload.values():
            yield from daily_sources(item)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            yield from daily_sources(item)


def assert_no_market_series(payload, internal_market_ids=()):
    assert list(daily_sources(payload)) == []
    serialized = json.dumps(payload, sort_keys=True)
    assert "#session=" not in serialized
    assert all(key not in serialized for key in internal_market_ids)
    for secret in (
        "__TIINGO_SECRET_SENTINEL__",
        "__OPENAI_SECRET_SENTINEL__",
        "__DEMO_ACCESS_SENTINEL__",
        "fixture@example.test",
        "__SEC_SENTINEL__",
        "TIINGO_API_TOKEN",
        "OPENAI_API_KEY",
        "DEMO_ACCESS_TOKEN",
        "Authorization",
    ):
        assert secret not in serialized


@pytest.fixture(params=["tiingo", "yahoo"])
def full_research(request):
    context = offline_context(request.param)
    registry = registry_for(context)

    class CapturingAgent(ResearchAgent):
        answer = None

        def execute_validated_plan(self, request, plan):
            self.answer = super().execute_validated_plan(request, plan)
            return self.answer

    llm = FakeLLMClient([cite_all_calculations])
    agent = CapturingAgent(registry=registry, llm=llm)
    response = ReportWorkflowService(agent).run(
        EquityResearchReportRequest(ticker="NVDA", as_of_date=AS_OF)
    )
    return context, registry, response, agent.answer, llm


def test_full_nvda_projection_and_internal_bundle_are_separate(full_research, tmp_path):
    context, registry, internal, answer, llm = full_research
    assert len(context.market.observations) == 501
    original_report, original_answer = internal.model_dump_json(), answer.model_dump_json()
    internal_refs = {row.canonical_id: row.evidence for row in internal.report.evidence_appendix}
    market = [ref for ref in internal_refs.values() if ref.kind == "SOURCE_FACT" and ref.date]
    assert Counter(ref.metric for ref in market) == {"close": 60, "high": 60, "low": 60}
    assert len({ref.date for ref in market}) == 60
    assert len(internal_refs) == 229
    assert len(internal.report.calculation_appendix) == 29
    # Internal values still reconstruct the exact adjusted fixture H/L/C.
    for field in ("close", "high", "low"):
        assert {ref.date: float(ref.value) for ref in market if ref.metric == field} == {
            bar.date: getattr(bar, field) for bar in context.market.observations[-60:]
        }
    projection = project_evidence(
        registry.get("equity_research").run(ticker="NVDA", as_of_date=AS_OF)
    )
    validate_grounding(
        SynthesisOutput.model_validate_json(cite_all_calculations(llm.requests[0])), projection
    )
    public = project_report(internal)
    assert public == project_report(internal)
    assert public.report.report_id == internal.report.report_id
    assert public.report.integrity == internal.report.integrity
    assert public.report.integrity_scope == "INTERNAL_RESEARCH_REPORT"
    assert public.report.projection_version == "public-research-projection-v1"
    assert len(public.report.evidence_appendix) == 52  # 20 SEC + 29 computations + 3 summaries.
    assert public.manifest_summary.evidence_count == 52
    assert public.manifest_summary.file_hashes is None
    assert_no_market_series(public.model_dump(mode="json"), [ref.evidence_id for ref in market])
    assert "#session=" not in public.markdown
    assert "withheld_market_input_count: 60" in public.markdown
    assert "internal_research_semantic_hash" in public.markdown
    for before, after in zip(
        internal.report.calculation_appendix, public.report.calculation_appendix, strict=True
    ):
        assert (
            after.result,
            after.result_unit,
            after.provenance.formula,
            after.provenance.parameters,
        ) == (
            before.result,
            before.result_unit,
            before.provenance.formula,
            before.provenance.parameters,
        )
        original_inputs = before.provenance.input_evidence_ids
        assert after.provenance.input_summary.input_count == len(original_inputs)
        if any(
            internal_refs[key].date and internal_refs[key].kind == "SOURCE_FACT"
            for key in original_inputs
        ):
            assert after.provenance.input_evidence_ids == after.input_display_aliases == ()
            assert after.provenance.input_summary.withheld_market_input_count == len(
                original_inputs
            )
        else:
            assert after.provenance.input_evidence_ids == original_inputs
    for row in public.report.evidence_appendix:
        if row.evidence.disclosure == "FULL_FACT":
            assert (
                row.evidence.model_dump(
                    exclude={
                        "disclosure",
                        "observation_count",
                        "input_range_start",
                        "input_range_end",
                        "internal_input_digest",
                    }
                )
                == internal_refs[row.canonical_id].model_dump()
            )
    public_answer = project_agent(answer)
    assert_no_market_series(
        public_answer.model_dump(mode="json"), [ref.evidence_id for ref in market]
    )
    assert [claim.statement for claim in public_answer.claims] == [
        claim.statement for claim in answer.claims
    ]
    for claim in public_answer.claims:
        assert set(claim.evidence_ids) <= public_answer.citations.keys()
    bundle = export_bundle(internal.report, tmp_path)
    ReportBundleValidator().validate_directory(bundle)
    assert len(list(daily_sources(json.loads((bundle / "evidence.json").read_text())))) == 180
    assert "#session=" in (bundle / "report.md").read_text()
    assert internal.model_dump_json() == original_report
    assert answer.model_dump_json() == original_answer


@pytest.mark.parametrize("lookback", [2, 60, 252, 501, 504])
def test_long_window_has_full_internal_inputs_but_no_public_series(lookback):
    context = offline_context("tiingo")

    class Builder:
        def build(self, **kwargs):
            return context

    internal = ResearchTools(Builder()).summarize_market_behavior(
        ticker="NVDA", as_of_date=AS_OF, lookback_sessions=lookback
    )
    original = internal.model_dump_json()
    public = project_tool_result(internal)
    assert public.model_dump()["window"] == internal.model_dump()["window"]
    assert public.model_dump()["latest_close"] == internal.latest_close
    if lookback <= 501:
        source = [ref for ref in internal.evidence if ref.kind == "SOURCE_FACT" and ref.date]
        # Short windows also retain SMA60 inputs; requested long windows retain full H/L/C.
        assert len({ref.date for ref in source}) == max(60, lookback)
        assert len([ref for ref in source if ref.metric == "close"]) == max(60, lookback)
        if lookback == 501:
            assert len(source) == 1503
            assert {ref.date: float(ref.value) for ref in source if ref.metric == "close"} == {
                bar.date: bar.close for bar in context.market.observations
            }
    assert_no_market_series(public.model_dump(mode="json"))
    assert all(not calc.input_evidence_ids for calc in public.calculation_provenance)
    assert internal.model_dump_json() == original


@pytest.mark.parametrize(
    "metric",
    [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adjClose",
        "adjVolume",
        "adjusted_high",
        "future_session_field",
    ],
)
def test_unknown_provider_and_adjusted_fields_are_internal_only(metric):
    ref = EvidenceReference(
        evidence_id="private-session",
        kind="SOURCE_FACT",
        metric=metric,
        provider="future-provider",
        source_reference="future:window#session=2026-06-30",
        date=AS_OF,
        value="123.456",
        unit="USD",
    )
    with pytest.raises(ValidationError):
        PublicEvidenceReference(**ref.model_dump(), disclosure="FULL_FACT")
    public, mapping = project_references((ref,))
    assert public[0].value is public[0].date is None
    assert mapping[ref.evidence_id] == public[0].evidence_id
    assert_no_market_series([row.model_dump(mode="json") for row in public])


def test_public_report_model_rejects_accidental_internal_response(full_research):
    _, _, internal, _, _ = full_research
    with pytest.raises(ValidationError):
        PublicResearchReport.model_validate(internal.report.model_dump())


def test_all_production_routes_project_after_access_gate(full_research, tmp_path):
    context, registry, internal, _, _ = full_research

    class Builder:
        def build(self, **kwargs):
            return context

    plan = json.dumps(
        {
            "plan_version": "1.0",
            "intent": "BROAD_RESEARCH",
            "selected_skill_id": "equity_research",
            "reason_code": "BROAD_EQUITY_RESEARCH_REQUEST",
            "ticker": "NVDA",
            "as_of_date": str(AS_OF),
            "requested_focus": None,
        }
    )
    llms = []

    def agent_factory():
        llm = FakeLLMClient(
            [
                lambda request: (
                    plan if request.phase == "PLANNING" else cite_all_calculations(request)
                ),
                cite_all_calculations,
            ]
        )
        llms.append(llm)
        return ResearchAgent(registry=registry, llm=llm)

    app = create_production_app(
        deployment_config=DeploymentConfig(
            environment="production",
            openai_key=SecretStr("__OPENAI_SECRET_SENTINEL__"),
            openai_model=SecretStr("synthetic-model"),
            openai_timeout_seconds=120,
            sec_user_agent=SecretStr("__SEC_SENTINEL__"),
            demo_access_token=SecretStr("__DEMO_ACCESS_SENTINEL__"),
            market_data_provider="tiingo",
            tiingo_api_token=SecretStr("__TIINGO_SECRET_SENTINEL__"),
        ),
        frontend_dir=tmp_path,
        agent_factory=agent_factory,
        tools_factory=lambda: ResearchTools(Builder()),
    )
    cases = [
        ("/v1/reports/equity-research", {"response_language": "ENGLISH"}),
        ("/v1/agent/research", {"question": REPORT_TASK_V1}),
        ("/v1/research/company-snapshot", {}),
        ("/v1/research/fundamental-trends", {"metrics": ["revenue"]}),
        ("/v1/research/compare-periods", {"metric": "revenue"}),
        ("/v1/research/market-behavior", {"lookback_sessions": 501}),
        ("/v1/research/quality", {}),
    ]
    with TestClient(app) as client:
        for endpoint, extra in cases:
            body = {"ticker": "NVDA", "as_of_date": str(AS_OF), **extra}
            assert client.post(endpoint, json=body).status_code == 401
            response = client.post(
                endpoint, json=body, headers={"X-Demo-Access": "__DEMO_ACCESS_SENTINEL__"}
            )
            assert response.status_code == 200, response.text
            assert_no_market_series(response.json())
            projected = response.json().get("report", response.json().get("data"))
            assert projected["projection_version"] == "public-research-projection-v1"
            if endpoint.endswith("market-behavior"):
                assert projected["window"]["lookback_sessions_available"] == 501
                assert projected["latest_close"] == context.market.observations[-1].close
                assert any(
                    calc["input_summary"]["input_count"] == 501
                    for calc in projected["calculation_provenance"]
                )
            if endpoint.endswith("company-snapshot"):
                assert projected["company"]["ticker"] == "NVDA"
                assert projected["fundamentals"]
            if endpoint.endswith("equity-research"):
                assert len(projected["calculation_appendix"]) == len(
                    internal.report.calculation_appendix
                )
        for path in ("/v1/evidence", "/v1/bundles", "/artifacts", "/market-data", "/download"):
            assert client.get(path).status_code == 404
    assert [llm.call_count for llm in llms] == [1, 2]


def test_chinese_public_markdown_uses_public_model(full_research):
    _, _, internal, _, _ = full_research
    translated = internal.model_copy(
        update={"report": internal.report.model_copy(update={"language": "CHINESE"})}
    )
    public = project_report(translated)
    assert "股票研究报告" in public.markdown
    assert "#session=" not in public.markdown
    assert "public-research-projection-v1" in public.markdown
