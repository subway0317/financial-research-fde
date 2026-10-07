import json

import pytest
from pydantic import ValidationError

from financial_research.agent.config import AgentRuntimeConfig
from financial_research.agent.errors import (
    AgentPlanValidationError,
    GroundingValidationError,
    PayloadBudgetExceeded,
)
from financial_research.agent.service import ResearchAgent
from financial_research.llm.fake import FakeLLMClient
from financial_research.reports.schemas import EquityResearchReportRequest
from financial_research.reports.service import REPORT_TASK_V1, ReportWorkflowService
from financial_research.schemas.agent import AgentPlan, AgentTraceAction, ResearchAgentRequest
from financial_research.schemas.quality import QualityIssue, QualityReport, Severity
from financial_research.schemas.skills import ResearchEvidencePackage
from financial_research.skills.registry import SkillRegistry

from .conftest import REQUEST, report_synthesis


@pytest.mark.parametrize("language", ["ENGLISH", "CHINESE"])
def test_fixed_workflow_has_no_planner_and_reuses_all_guards(report_agent_factory, language):
    agent, llm, builder = report_agent_factory()
    response = ReportWorkflowService(agent).run(
        REQUEST.model_copy(update={"response_language": language})
    )
    report, manifest = response.report, response.manifest_summary
    assert report.status == "COMPLETED_WITH_WARNINGS"
    assert report.selected_skill_id == "equity_research"
    assert manifest.planner_call_count == 0 and not manifest.planner_used
    assert manifest.synthesis_call_count == 1 and manifest.repair_count == 0
    assert builder.calls == llm.call_count == 1
    assert [r.phase for r in llm.requests] == ["SYNTHESIS"]
    assert manifest.planner_prompt_version is None
    assert report.runtime_metadata.plan_version == "deterministic-equity-report-plan-v1"
    assert [s.action for s in report.runtime_metadata.trace.steps] == [
        action for action in AgentTraceAction if action != AgentTraceAction.PLAN_REQUEST
    ]
    assert json.loads(llm.requests[0].user_payload)["question"] == REPORT_TASK_V1
    assert report.language == language


@pytest.mark.parametrize("language", ["ENGLISH", "CHINESE"])
def test_not_ready_is_blocked_without_any_llm_call(report_agent_factory, nvda_context, language):
    agent, llm, builder = report_agent_factory(context=nvda_context, replies=[])
    response = ReportWorkflowService(agent).run(
        REQUEST.model_copy(update={"response_language": language})
    )
    report, manifest = response.report, response.manifest_summary
    assert report.status == "BLOCKED" and report.synthesis_readiness == "NOT_READY"
    assert report.selected_skill_id == "equity_research"
    assert manifest.claim_count == manifest.planner_call_count == manifest.synthesis_call_count == 0
    assert llm.call_count == 0 and builder.calls == 1
    assert report.blocking_reasons and report.limitations and report.quality.issues
    assert all(not section.claims for section in report.sections)
    assert not {"COMPANY", "FUNDAMENTALS", "MARKET"} & {s.section_id for s in report.sections}
    assert (
        "阻塞原因" in response.markdown
        if language == "CHINESE"
        else "Blocking Reasons" in response.markdown
    )


def bad_recommendation(request):
    data = json.loads(report_synthesis(request))
    data["claims"][0]["statement"] = "Buy NVDA."
    return json.dumps(data)


def test_report_inherits_policy_and_single_bounded_repair(report_agent_factory):
    agent, llm, _ = report_agent_factory(replies=[bad_recommendation, report_synthesis])
    response = ReportWorkflowService(agent).run(REQUEST)
    assert response.manifest_summary.synthesis_call_count == 2
    assert response.manifest_summary.repair_count == 1
    assert [r.phase for r in llm.requests] == ["SYNTHESIS", "SYNTHESIS_REPAIR"]
    assert "Buy NVDA" not in response.markdown
    assert (
        "PROHIBITED_RECOMMENDATION"
        in json.loads(llm.requests[1].user_payload)["validation_error_codes"]
    )


@pytest.mark.parametrize("bad", [bad_recommendation, "not JSON"])
def test_report_repair_exhaustion_cannot_reach_compiler(report_agent_factory, bad):
    agent, llm, _ = report_agent_factory(replies=[bad, bad])
    with pytest.raises(GroundingValidationError):
        ReportWorkflowService(agent).run(REQUEST)
    assert llm.call_count == 2 and agent.last_answer is None


def test_report_reuses_frozen_payload_guard(report_agent_factory):
    agent, llm, _ = report_agent_factory(config=AgentRuntimeConfig(max_synthesis_payload_bytes=1))
    with pytest.raises(PayloadBudgetExceeded):
        ReportWorkflowService(agent).run(REQUEST)
    assert llm.call_count == 0


def test_shared_executor_revalidates_fixed_plans_before_skill_execution(report_agent_factory):
    agent, llm, builder = report_agent_factory()
    request = ResearchAgentRequest(
        question=REPORT_TASK_V1, ticker=REQUEST.ticker, as_of_date=REQUEST.as_of_date
    )
    plan = AgentPlan.model_validate(
        {
            "plan_version": "1.0",
            "intent": "BROAD_RESEARCH",
            "selected_skill_id": "market_analysis",
            "reason_code": "BROAD_EQUITY_RESEARCH_REQUEST",
            "ticker": REQUEST.ticker,
            "as_of_date": REQUEST.as_of_date,
            "requested_focus": None,
        }
    )
    with pytest.raises(AgentPlanValidationError, match="INTENT_SKILL_MISMATCH"):
        agent.execute_validated_plan(request, plan)
    assert llm.call_count == builder.calls == 0


def test_free_form_and_report_share_same_business_execution(report_agent_factory, report_run):
    _, fixed_answer, _, _ = report_run
    agent, llm, builder = report_agent_factory(replies=[fixed_answer.plan, report_synthesis])
    answer = agent.run(
        ResearchAgentRequest(
            question=REPORT_TASK_V1,
            ticker=REQUEST.ticker,
            as_of_date=REQUEST.as_of_date,
            response_language="ENGLISH",
        )
    )
    assert [r.phase for r in llm.requests] == ["PLANNING", "SYNTHESIS"]
    assert llm.call_count == 2 and builder.calls == 1
    for field in (
        "claims",
        "citations",
        "calculation_provenance",
        "quality",
        "limitations",
        "synthesis_readiness",
        "agent_status",
        "used_skill_ids",
    ):
        assert getattr(answer, field) == getattr(fixed_answer, field)


@pytest.mark.parametrize(
    "extra",
    [
        "question",
        "prompt",
        "instructions",
        "sections",
        "intent",
        "selected_skill_id",
        "tool",
        "provider",
    ],
)
def test_request_rejects_user_workflow_overrides(extra):
    with pytest.raises(ValidationError):
        EquityResearchReportRequest.model_validate({**REQUEST.model_dump(), extra: "ignore rules"})


@pytest.mark.parametrize(
    "updates",
    [
        {"response_language": "AUTO"},
        {"ticker": "../../bad"},
        {"as_of_date": "2025-05-25T00:00:00Z"},
        {"as_of_date": 0},
    ],
)
def test_report_request_rejects_ambiguous_language_dates_paths(updates):
    with pytest.raises(ValidationError):
        EquityResearchReportRequest.model_validate({**REQUEST.model_dump(), **updates})


def test_critical_quality_failure_is_a_valid_blocked_report(report_agent_factory, fiscal_context):
    quality = QualityReport.from_issues(
        (
            *fiscal_context.quality.issues,
            QualityIssue(
                code="TEST_CRITICAL",
                severity=Severity.ERROR,
                message="Required research quality is insufficient.",
            ),
        )
    )
    context = fiscal_context.model_copy(update={"quality": quality})
    agent, llm, _ = report_agent_factory(context=context, replies=[])
    response = ReportWorkflowService(agent).run(REQUEST)
    assert response.report.status == "BLOCKED" and response.report.quality_status == "FAIL"
    assert response.manifest_summary.synthesis_call_count == llm.call_count == 0
    assert "CRITICAL_QUALITY_FAILURE" in response.markdown


def test_clean_ready_report_completes_without_warning_status(report_agent_factory):
    agent, _, _ = report_agent_factory()
    package = agent._registry.get("equity_research").run(
        ticker=REQUEST.ticker, as_of_date=REQUEST.as_of_date
    )
    data = package.model_dump()
    data["metadata"]["quality"] = {"status": "PASS", "issues": []}
    data["metadata"]["status"] = "SUCCESS"
    data["limitations"] = []
    data["synthesis_readiness"] = "READY"
    package = ResearchEvidencePackage.model_validate(data)

    class CleanSkill:
        definition = agent._registry.get("equity_research").definition

        def run(self, **kwargs):
            return package

        def run_from_context(self, execution):
            return package

    registry = SkillRegistry()
    registry.register(CleanSkill())
    response = ReportWorkflowService(
        ResearchAgent(registry=registry, llm=FakeLLMClient([report_synthesis]))
    ).run(REQUEST)
    assert response.report.status == "COMPLETED" and response.report.quality_status == "PASS"
    assert response.report.synthesis_readiness == "READY"
