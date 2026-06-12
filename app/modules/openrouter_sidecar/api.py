from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth.dependencies import set_dashboard_error_format, validate_dashboard_session
from app.dependencies import OpenRouterSidecarContext, get_openrouter_sidecar_context
from app.modules.openrouter_sidecar.schemas import (
    OpenRouterSidecarModelsResponse,
    OpenRouterSidecarStatusResponse,
    OpenRouterSidecarTestResponse,
)

router = APIRouter(
    prefix="/api/openrouter-sidecar",
    tags=["dashboard"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


@router.get("/status", response_model=OpenRouterSidecarStatusResponse)
async def get_status(
    context: OpenRouterSidecarContext = Depends(get_openrouter_sidecar_context),
) -> OpenRouterSidecarStatusResponse:
    return await context.service.get_status()


@router.post("/test", response_model=OpenRouterSidecarTestResponse)
async def test_connection(
    context: OpenRouterSidecarContext = Depends(get_openrouter_sidecar_context),
) -> OpenRouterSidecarTestResponse:
    return await context.service.test_connection()


@router.get("/models", response_model=OpenRouterSidecarModelsResponse)
async def list_models(
    context: OpenRouterSidecarContext = Depends(get_openrouter_sidecar_context),
) -> OpenRouterSidecarModelsResponse:
    return await context.service.list_models()
