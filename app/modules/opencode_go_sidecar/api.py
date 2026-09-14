from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth.dependencies import set_dashboard_error_format, validate_dashboard_session
from app.dependencies import OpenCodeGoSidecarContext, get_opencode_go_sidecar_context
from app.modules.opencode_go_sidecar.schemas import (
    OpenCodeGoSidecarModelsResponse,
    OpenCodeGoSidecarStatusResponse,
    OpenCodeGoSidecarTestResponse,
)

router = APIRouter(
    prefix="/api/opencode-go-sidecar",
    tags=["dashboard"],
    # Every route here reads or exercises a stored subscription credential, so
    # all of them sit behind the dashboard session, never the proxy API key.
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


@router.get("/status", response_model=OpenCodeGoSidecarStatusResponse)
async def get_status(
    context: OpenCodeGoSidecarContext = Depends(get_opencode_go_sidecar_context),
) -> OpenCodeGoSidecarStatusResponse:
    return await context.service.get_status()


@router.post("/test", response_model=OpenCodeGoSidecarTestResponse)
async def test_connection(
    context: OpenCodeGoSidecarContext = Depends(get_opencode_go_sidecar_context),
) -> OpenCodeGoSidecarTestResponse:
    return await context.service.test_connection()


@router.get("/models", response_model=OpenCodeGoSidecarModelsResponse)
async def list_models(
    context: OpenCodeGoSidecarContext = Depends(get_opencode_go_sidecar_context),
) -> OpenCodeGoSidecarModelsResponse:
    return await context.service.list_models()
