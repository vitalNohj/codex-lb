from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth.dependencies import set_dashboard_error_format, validate_dashboard_session
from app.dependencies import OrcaRouterSidecarContext, get_orcarouter_sidecar_context
from app.modules.orcarouter_sidecar.schemas import (
    OrcaRouterSidecarModelsResponse,
    OrcaRouterSidecarStatusResponse,
    OrcaRouterSidecarTestResponse,
)

router = APIRouter(
    prefix="/api/orcarouter-sidecar",
    tags=["dashboard"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


@router.get("/status", response_model=OrcaRouterSidecarStatusResponse)
async def get_status(
    context: OrcaRouterSidecarContext = Depends(get_orcarouter_sidecar_context),
) -> OrcaRouterSidecarStatusResponse:
    return await context.service.get_status()


@router.post("/test", response_model=OrcaRouterSidecarTestResponse)
async def test_connection(
    context: OrcaRouterSidecarContext = Depends(get_orcarouter_sidecar_context),
) -> OrcaRouterSidecarTestResponse:
    return await context.service.test_connection()


@router.get("/models", response_model=OrcaRouterSidecarModelsResponse)
async def list_models(
    context: OrcaRouterSidecarContext = Depends(get_orcarouter_sidecar_context),
) -> OrcaRouterSidecarModelsResponse:
    return await context.service.list_models()
