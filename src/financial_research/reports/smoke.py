"""Opt-in real-provider report E2E smoke, without the evaluation-time Judge."""

import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from financial_research.api.runtime import live_agent
from financial_research.exceptions import ConfigurationError, FinancialResearchError, ProviderError
from financial_research.llm.errors import AgentConfigurationError, LLMProviderError
from financial_research.reports.cli import generate_and_export, parser, request_from_args
from financial_research.reports.schemas import EquityResearchReportRequest, ReportStatus
from financial_research.reports.service import ReportWorkflowService


def run_live_report_smoke(
    request: EquityResearchReportRequest,
    output_dir: Path = Path("artifacts/reports"),
    *,
    service: ReportWorkflowService | None = None,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "ticker": request.ticker,
        "as_of_date": str(request.as_of_date),
        "language": request.response_language,
    }
    if service is None:
        missing = [
            name
            for name in (
                "OPENAI_API_KEY",
                "OPENAI_MODEL",
                "SEC_USER_AGENT",
                "OPENAI_TIMEOUT_SECONDS",
            )
            if not os.environ.get(name)
        ]
        if missing:
            return {
                **summary,
                "smoke_status": "USER_CONFIGURATION_REQUIRED",
                "missing_configuration": missing,
            }
    try:
        if service is None:
            with live_agent() as agent:
                result = generate_and_export(ReportWorkflowService(agent), request, output_dir)
        else:
            result = generate_and_export(service, request, output_dir)
    except (AgentConfigurationError, ConfigurationError):
        return {
            **summary,
            "smoke_status": "USER_CONFIGURATION_REQUIRED",
            "error_code": "CONFIGURATION_ERROR",
        }
    except LLMProviderError as exc:
        return {
            **summary,
            "smoke_status": "FAIL" if exc.http_status in {400, 404, 422} else "EXTERNAL_BLOCKED",
            "error_code": "LLM_PROVIDER_ERROR",
        }
    except ProviderError:
        return {**summary, "smoke_status": "EXTERNAL_BLOCKED", "error_code": "PROVIDER_ERROR"}
    except FinancialResearchError as exc:
        return {**summary, "smoke_status": "FAIL", "error_code": type(exc).__name__}
    passed = (
        result["status"] in {ReportStatus.COMPLETED, ReportStatus.COMPLETED_WITH_WARNINGS}
        and result["selected_skill"] == "equity_research"
        and result["planner_calls"] == 0
        and result["synthesis_calls"] in {1, 2}
        and isinstance(result["claim_count"], int)
        and result["claim_count"] > 0
        and isinstance(result["evidence_count"], int)
        and result["evidence_count"] > 0
        and result["bundle_integrity"] == "PASS"
        and result["pit_violation_count"] == 0
    )
    return {**result, "smoke_status": "PASS" if passed else "FAIL"}


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        request = request_from_args(args)
    except ValidationError:
        sys.stderr.write("INVALID_REPORT_REQUEST\n")
        return 1
    result = run_live_report_smoke(request, args.output_dir)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    codes = {"PASS": 0, "USER_CONFIGURATION_REQUIRED": 3, "EXTERNAL_BLOCKED": 2, "FAIL": 1}
    return codes[str(result["smoke_status"])]


if __name__ == "__main__":
    sys.exit(main())
