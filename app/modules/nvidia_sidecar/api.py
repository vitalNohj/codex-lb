from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth.dependencies import set_dashboard_error_format, validate_dashboard_session
from app.dependencies import NvidiaSidecarContext, get_nvidia_sidecar_context
from app.modules.nvidia_sidecar.schemas import (
    NvidiaSidecarModelsResponse,
    NvidiaSidecarStatusResponse,
    NvidiaSidecarTestResponse,
)

router = APIRouter(
    prefix="/api/nvidia-sidecar",
    tags=["dashboard"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


@router.get("/status", response_model=NvidiaSidecarStatusResponse)
async def get_status(
    context: NvidiaSidecarContext = Depends(get_nvidia_sidecar_context),
) -> NvidiaSidecarStatusResponse:
    return await context.service.get_status()


@router.post("/test", response_model=NvidiaSidecarTestResponse)
async def test_connection(
    context: NvidiaSidecarContext = Depends(get_nvidia_sidecar_context),
) -> NvidiaSidecarTestResponse:
    return await context.service.test_connection()


@router.get("/models", response_model=NvidiaSidecarModelsResponse)
async def list_models(
    context: NvidiaSidecarContext = Depends(get_nvidia_sidecar_context),
) -> NvidiaSidecarModelsResponse:
    return await context.service.list_models()
