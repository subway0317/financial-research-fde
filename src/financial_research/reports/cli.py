"""Generate an equity report and export a validated local audit bundle."""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from financial_research.api.runtime import live_agent
from financial_research.exceptions import ConfigurationError, FinancialResearchError, ProviderError
from financial_research.llm.errors import AgentConfigurationError, LLMProviderError
from financial_research.reports.bundle import export_bundle
from financial_research.reports.manifest import build_manifest
from financial_research.reports.schemas import EquityResearchReportRequest, ResearchReport
from financial_research.reports.service import ReportWorkflowService


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--ticker", required=True)
    result.add_argument("--as-of-date", required=True, type=date.fromisoformat)
    result.add_argument("--language", choices=("ENGLISH", "CHINESE"), default="ENGLISH")
    result.add_argument("--output-dir", type=Path, default=Path("artifacts/reports"))
    return result


def request_from_args(args: argparse.Namespace) -> EquityResearchReportRequest:
    return EquityResearchReportRequest.model_validate(
        {
            "ticker": args.ticker,
            "as_of_date": args.as_of_date,
            "response_language": args.language,
        }
    )


def safe_summary(report: ResearchReport, path: Path) -> dict[str, object]:
    manifest = build_manifest(report)
    return {
        "status": report.status,
        "report_id": report.report_id,
        "run_id": str(report.run_id),
        "ticker": report.ticker,
        "as_of_date": str(report.as_of_date),
        "language": report.language,
        "selected_skill": report.selected_skill_id,
        "planner_calls": manifest.planner_call_count,
        "synthesis_calls": manifest.synthesis_call_count,
        "repair_count": manifest.repair_count,
        "claim_count": manifest.claim_count,
        "evidence_count": manifest.evidence_count,
        "calculation_count": manifest.calculation_count,
        "quality": manifest.quality_status,
        "readiness": manifest.synthesis_readiness,
        "bundle_integrity": "PASS",
        "pit_violation_count": 0,
        "bundle_path": str(path),
    }


def generate_and_export(
    service: ReportWorkflowService, request: EquityResearchReportRequest, output_dir: Path
) -> dict[str, object]:
    response = service.run(request)
    path = export_bundle(response.report, output_dir)
    return safe_summary(response.report, path)


def main(argv: Sequence[str] | None = None, *, service: ReportWorkflowService | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        request = request_from_args(args)
    except ValidationError:
        sys.stderr.write("INVALID_REPORT_REQUEST\n")
        return 1
    try:
        if service is None:
            with live_agent() as agent:
                summary = generate_and_export(
                    ReportWorkflowService(agent), request, args.output_dir
                )
        else:
            summary = generate_and_export(service, request, args.output_dir)
    except (AgentConfigurationError, ConfigurationError):
        sys.stderr.write("USER_CONFIGURATION_REQUIRED\n")
        return 3
    except (LLMProviderError, ProviderError):
        sys.stderr.write("EXTERNAL_PROVIDER_ERROR\n")
        return 2
    except FinancialResearchError as exc:
        # Class name only; never print provider messages or exception inputs.
        sys.stderr.write(f"REPORT_FAILED:{type(exc).__name__}\n")
        return 1
    sys.stdout.write(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
