"""Thin stateless report transport; local export is a separate CLI operation."""

from typing import Annotated

from fastapi import APIRouter, Depends

from financial_research.api.dependencies import get_report_workflow
from financial_research.reports.schemas import (
    EquityResearchReportRequest,
    EquityResearchReportResponse,
)
from financial_research.reports.service import ReportWorkflowService

router = APIRouter(prefix="/v1/reports", tags=["reports"])


@router.post("/equity-research", response_model=EquityResearchReportResponse)
def equity_research(
    body: EquityResearchReportRequest,
    service: Annotated[ReportWorkflowService, Depends(get_report_workflow)],
) -> EquityResearchReportResponse:
    return service.run(body)
