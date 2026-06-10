from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth.dependencies import set_dashboard_error_format, validate_dashboard_session
from app.dependencies import ClaudeSidecarContext, get_claude_sidecar_context
from app.modules.claude_sidecar.schemas import (
    ClaudeSidecarModelsResponse,
    ClaudeSidecarQuotaResponse,
    ClaudeSidecarStatusResponse,
    ClaudeSidecarTestResponse,
)

router = APIRouter(
    prefix="/api/claude-sidecar",
    tags=["dashboard"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


@router.get("/status", response_model=ClaudeSidecarStatusResponse)
async def get_status(
    context: ClaudeSidecarContext = Depends(get_claude_sidecar_context),
) -> ClaudeSidecarStatusResponse:
    return await context.service.get_status()


@router.post("/test", response_model=ClaudeSidecarTestResponse)
async def test_connection(
    context: ClaudeSidecarContext = Depends(get_claude_sidecar_context),
) -> ClaudeSidecarTestResponse:
    return await context.service.test_connection()


@router.get("/models", response_model=ClaudeSidecarModelsResponse)
async def list_models(
    context: ClaudeSidecarContext = Depends(get_claude_sidecar_context),
) -> ClaudeSidecarModelsResponse:
    return await context.service.list_models()


@router.get("/quota", response_model=ClaudeSidecarQuotaResponse)
async def get_quota(
    context: ClaudeSidecarContext = Depends(get_claude_sidecar_context),
) -> ClaudeSidecarQuotaResponse:
    return await context.service.get_quota()
