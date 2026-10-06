"""Process liveness is independent of all external providers."""

from fastapi import APIRouter

from financial_research.api.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()
