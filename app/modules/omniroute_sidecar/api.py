from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth.dependencies import set_dashboard_error_format, validate_dashboard_session
from app.dependencies import OmniRouteSidecarContext, get_omniroute_sidecar_context
from app.modules.omniroute_sidecar.schemas import (
    OmniRouteSidecarModelsResponse,
    OmniRouteSidecarStatusResponse,
    OmniRouteSidecarTestResponse,
)

router = APIRouter(
    prefix="/api/omniroute-sidecar",
    tags=["dashboard"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


@router.get("/status", response_model=OmniRouteSidecarStatusResponse)
async def get_status(
    context: OmniRouteSidecarContext = Depends(get_omniroute_sidecar_context),
) -> OmniRouteSidecarStatusResponse:
    return await context.service.get_status()


@router.post("/test", response_model=OmniRouteSidecarTestResponse)
async def test_connection(
    context: OmniRouteSidecarContext = Depends(get_omniroute_sidecar_context),
) -> OmniRouteSidecarTestResponse:
    return await context.service.test_connection()


@router.get("/models", response_model=OmniRouteSidecarModelsResponse)
async def list_models(
    context: OmniRouteSidecarContext = Depends(get_omniroute_sidecar_context),
) -> OmniRouteSidecarModelsResponse:
    return await context.service.list_models()
