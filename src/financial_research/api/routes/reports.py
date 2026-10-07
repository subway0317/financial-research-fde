"""Thin stateless report transport; local export is a separate CLI operation."""

from typing import Annotated

from fastapi import APIRouter, Depends

from financial_research.api.dependencies import get_report_workflow
from financial_research.api.schemas import ErrorResponse
from financial_research.public_research.projection import project_report
from financial_research.public_research.schemas import PublicEquityResearchReportResponse
from financial_research.reports.schemas import (
    EquityResearchReportRequest,
)
from financial_research.reports.service import ReportWorkflowService

router = APIRouter(
    prefix="/v1/reports",
    tags=["reports"],
    responses={status: {"model": ErrorResponse} for status in (422, 404, 502, 503, 500)},
)


@router.post("/equity-research", response_model=PublicEquityResearchReportResponse)
def equity_research(
    body: EquityResearchReportRequest,
    service: Annotated[ReportWorkflowService, Depends(get_report_workflow)],
) -> PublicEquityResearchReportResponse:
    return project_report(service.run(body))
