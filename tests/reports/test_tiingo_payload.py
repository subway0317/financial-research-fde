"""Offline Stage 8 production shape: real providers/core/Skills, fake synthesis.

Prices are the existing Tiingo NVDA fixture. Fundamentals below are explicitly
synthetic fiscal facts, corroborated through synthetic SEC submissions; they are
not actual NVDA financial statements. Yahoo receives identical financial bars.
"""

import json
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from financial_research.agent.config import AgentRuntimeConfig
from financial_research.agent.errors import PayloadBudgetExceeded
from financial_research.agent.evidence_projection import project_evidence
from financial_research.agent.grounding import validate_grounding
from financial_research.agent.service import ResearchAgent
from financial_research.agent.synthesis_payload import synthesis_payload
from financial_research.company.service import CompanyService
from financial_research.fundamentals.service import FundamentalService
from financial_research.llm.fake import FakeLLMClient
from financial_research.market.service import MarketService
from financial_research.providers.market import YahooMarketProvider
from financial_research.providers.sec import SECProvider
from financial_research.providers.tiingo import TiingoMarketProvider
from financial_research.reports.bundle import export_bundle
from financial_research.reports.schemas import EquityResearchReportRequest
from financial_research.reports.service import REPORT_TASK_V1, ReportWorkflowService
from financial_research.reports.validation import ReportBundleValidator
from financial_research.research.context import ResearchContextBuilder
from financial_research.schemas.agent import (
    AgentPlan,
    ResearchAgentRequest,
    ResponseLanguage,
    SynthesisOutput,
)
from financial_research.skills.defaults import create_skill_registry
from financial_research.skills.registry import SkillRegistry

from .conftest import report_synthesis

AS_OF = date(2026, 6, 30)


def offline_context(provider):
    fixtures = Path(__file__).parents[1] / "fixtures"
    sample = json.loads((fixtures / "tiingo/nvda_730.json").read_text())
    directory = json.loads((fixtures / "sec_directory.json").read_text())
    concepts = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": 100,
        "GrossProfit": 60,
        "OperatingIncomeLoss": 30,
        "NetIncomeLoss": 25,
        "NetCashProvidedByUsedInOperatingActivities": 40,
        "PaymentsToAcquirePropertyPlantAndEquipment": 10,
        "CashAndCashEquivalentsAtCarryingValue": 50,
        "Assets": 200,
        "Liabilities": 80,
        "StockholdersEquity": 120,
    }
    instant = {
        "CashAndCashEquivalentsAtCarryingValue",
        "Assets",
        "Liabilities",
        "StockholdersEquity",
    }
    facts = {}
    for concept, value in concepts.items():
        rows = []
        for year, scale in ((2025, 1), (2026, 1.5)):
            row = {
                "end": f"{year}-03-31",
                "filed": f"{year}-05-21",
                "form": "10-Q",
                "accn": f"offline-{year}-q1",
                "fy": year,
                "fp": "Q1",
                "val": int(value * scale),
            }
            if concept not in instant:
                row["start"] = f"{year}-01-01"
            rows.append(row)
        facts[concept] = {"units": {"USD": rows}}
    fundamentals = {
        "cik": 1045810,
        "entityName": "Synthetic NVDA fixture",
        "facts": {"us-gaap": facts},
    }
    submissions = {
        "cik": "1045810",
        "filings": {
            "recent": {
                "accessionNumber": ["offline-2026-q1", "offline-2025-q1"],
                "reportDate": ["2026-03-31", "2025-03-31"],
                "filingDate": ["2026-05-21", "2025-05-21"],
                "form": ["10-Q", "10-Q"],
            },
            "files": [],
        },
    }
    rows = sample["prices"]
    chart = {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {
                        "symbol": "NVDA",
                        "currency": "USD",
                        "exchangeTimezoneName": "America/New_York",
                    },
                    "timestamp": [
                        int(
                            datetime.combine(
                                date.fromisoformat(row["date"][:10]),
                                time(9, 30),
                                ZoneInfo("America/New_York"),
                            ).timestamp()
                        )
                        for row in rows
                    ],
                    "indicators": {
                        "quote": [
                            {
                                field: [
                                    row["adjVolume"] if field == "volume" else row[field]
                                    for row in rows
                                ]
                                for field in ("open", "high", "low", "close", "volume")
                            }
                        ],
                        "adjclose": [{"adjclose": [row["adjClose"] for row in rows]}],
                    },
                }
            ],
        }
    }

    def handler(request):
        if request.url.host == "api.tiingo.com":
            payload = (
                sample["prices"] if request.url.path.endswith("/prices") else sample["metadata"]
            )
        elif request.url.host == "query1.finance.yahoo.com":
            payload = chart
        elif request.url.path.endswith("company_tickers_exchange.json"):
            payload = directory
        elif "/companyfacts/" in request.url.path:
            payload = fundamentals
        else:
            assert request.url.path == "/submissions/CIK0001045810.json"
            payload = submissions
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        sec = SECProvider(
            user_agent="Fixture fixture@example.test",
            client=client,
            fiscal_metadata_start=date(2024, 6, 30),
            fiscal_metadata_end=AS_OF,
        )
        market = (
            TiingoMarketProvider(api_token="__TIINGO_SECRET_SENTINEL__", client=client)
            if provider == "tiingo"
            else YahooMarketProvider(client=client)
        )
        return ResearchContextBuilder(
            company_service=CompanyService(sec),
            market_service=MarketService(market),
            fundamental_service=FundamentalService(sec),
        ).build(ticker="NVDA", as_of_date=AS_OF)


def registry_for(context):
    class Builder:
        def build(self, *, ticker, as_of_date):
            assert (ticker, as_of_date) == ("NVDA", AS_OF)
            return context

    return create_skill_registry(Builder())


def restore_provenance(data):
    """Recover the exact previous wire projection, not a lossy semantic comparison."""
    restored = {key: value for key, value in data.items() if key != "provenance_index"}
    restored["projection_version"] = "2.0"
    restored["evidence_index"] = {
        key: {
            **{field: value for field, value in ref.items() if field != "provenance_id"},
            **data["provenance_index"][ref["provenance_id"]],
        }
        for key, ref in data["evidence_index"].items()
    }
    return restored


def cite_all_calculations(request):
    output = json.loads(report_synthesis(request))
    projection = json.loads(request.user_payload)["projection"]
    output["claims"].append(
        {
            "claim_id": "calculation_coverage",
            "section": "MARKET",
            "claim_type": "INTERPRETATION",
            "statement": "The supplied evidence includes deterministic descriptive calculations.",
            "evidence_ids": list(projection["calculation_provenance"]),
        }
    )
    return json.dumps(output)


@pytest.mark.parametrize("provider", ["tiingo", "yahoo"])
def test_full_report_fits_frozen_budget_without_losing_evidence_or_audit(
    provider, tmp_path, caplog
):
    context = offline_context(provider)
    registry = registry_for(context)
    result = registry.get("equity_research").run(ticker="NVDA", as_of_date=AS_OF)
    projection = project_evidence(result)
    original = projection.model_dump_json()
    assert projection.synthesis_readiness == "READY_WITH_WARNINGS"
    payload, audit = synthesis_payload(
        question=REPORT_TASK_V1, projection=projection, response_language=ResponseLanguage.ENGLISH
    )
    data = json.loads(payload)["projection"]
    limit = AgentRuntimeConfig().max_synthesis_payload_bytes
    assert limit == 200_000
    assert audit.request_bytes == len(payload.encode("utf-8")) <= limit
    restored = restore_provenance(data)
    assert restored["evidence_index"] == {
        key: ref.model_dump(mode="json", exclude_none=True, exclude={"evidence_id"})
        for key, ref in projection.evidence_index.items()
    }
    legacy = {**json.loads(payload), "projection": restored}
    legacy_bytes = len(json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    assert (legacy_bytes > limit) == (provider == "tiingo")
    market = [
        ref
        for ref in data["evidence_index"].values()
        if ref["kind"] == "SOURCE_FACT" and ref["metric"] in {"close", "high", "low"}
    ]
    assert len(market) == 180
    assert len({ref["source_reference"] for ref in market}) == 180
    assert len({ref["provenance_id"] for ref in market}) == 1
    for calc in data["calculation_provenance"].values():
        assert set(calc["input_evidence_ids"]) <= data["evidence_index"].keys()
    llm = FakeLLMClient([cite_all_calculations])
    response = ReportWorkflowService(ResearchAgent(registry=registry, llm=llm)).run(
        EquityResearchReportRequest(ticker="NVDA", as_of_date=AS_OF, response_language="ENGLISH")
    )
    assert response.report.status == "COMPLETED_WITH_WARNINGS"
    assert llm.call_count == 1
    assert llm.requests[0].user_payload == payload
    assert (
        response.manifest_summary.planner_call_count == response.manifest_summary.repair_count == 0
    )
    assert response.report.quality == projection.quality
    assert response.report.limitations == projection.limitations
    assert {entry.canonical_id: entry.evidence for entry in response.report.evidence_appendix} == (
        projection.evidence_index
    )
    assert {
        entry.canonical_id: entry.provenance for entry in response.report.calculation_appendix
    } == {calc.evidence_id: calc for calc in projection.calculation_provenance}
    validate_grounding(
        SynthesisOutput.model_validate_json(cite_all_calculations(llm.requests[0])), projection
    )
    bundle = export_bundle(response.report, tmp_path)
    ReportBundleValidator().validate_directory(bundle)
    evidence = json.loads((bundle / "evidence.json").read_text())
    assert {
        entry["canonical_id"]: entry["evidence"] for entry in evidence["evidence_appendix"]
    } == {key: ref.model_dump(mode="json") for key, ref in projection.evidence_index.items()}
    assert projection.model_dump_json() == original
    assert "__TIINGO_SECRET_SENTINEL__" not in payload + caplog.text
    assert (
        "fixture@example.test" not in payload + caplog.text + (bundle / "evidence.json").read_text()
    )


def test_provider_invariance_of_financial_evidence():
    tiingo, yahoo = (offline_context(provider) for provider in ("tiingo", "yahoo"))
    assert [
        bar.model_dump(exclude={"provider", "retrieved_at"}) for bar in tiingo.market.observations
    ] == [bar.model_dump(exclude={"provider", "retrieved_at"}) for bar in yahoo.market.observations]
    assert tiingo.market.features == yahoo.market.features
    assert [
        row.model_dump(exclude={"retrieved_at"}) for row in tiingo.fundamentals.observations
    ] == [row.model_dump(exclude={"retrieved_at"}) for row in yahoo.fundamentals.observations]


def test_genuinely_large_financial_input_closure_is_still_rejected():
    context = offline_context("tiingo")
    registered = registry_for(context).get("market_analysis")
    # Exercise an existing supported long window, without altering the default
    # 60-session production path or adding/truncating any evidence.
    result = registered.run(ticker="NVDA", as_of_date=AS_OF, lookback_sessions=501)
    projection = project_evidence(result)
    assert projection.synthesis_readiness == "READY_WITH_WARNINGS"
    payload, _ = synthesis_payload(
        question=REPORT_TASK_V1, projection=projection, response_language=ResponseLanguage.ENGLISH
    )
    assert len(payload.encode("utf-8")) > 200_000

    class LargeWindowSkill:
        definition = registered.definition

        def run(self, *, ticker, as_of_date):
            assert (ticker, as_of_date) == ("NVDA", AS_OF)
            return result

    registry = SkillRegistry()
    registry.register(LargeWindowSkill())
    llm = FakeLLMClient([])
    plan = AgentPlan(
        plan_version="1.0",
        intent="MARKET_FOCUS",
        selected_skill_id="market_analysis",
        reason_code="MARKET_ANALYSIS_REQUEST",
        ticker="NVDA",
        as_of_date=AS_OF,
        requested_focus=None,
    )
    with pytest.raises(PayloadBudgetExceeded) as failure:
        ResearchAgent(registry=registry, llm=llm).execute_validated_plan(
            ResearchAgentRequest(
                question=REPORT_TASK_V1,
                ticker="NVDA",
                as_of_date=AS_OF,
                response_language="ENGLISH",
            ),
            plan,
        )
    assert failure.value.code == "SYNTHESIS_PAYLOAD_BUDGET_EXCEEDED"
    assert failure.value.actual_bytes == len(payload.encode("utf-8"))
    assert failure.value.budget_bytes == 200_000
    assert llm.call_count == 0
