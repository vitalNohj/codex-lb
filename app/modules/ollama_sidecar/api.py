from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth.dependencies import set_dashboard_error_format, validate_dashboard_session
from app.dependencies import OllamaSidecarContext, get_ollama_sidecar_context
from app.modules.ollama_sidecar.schemas import (
    OllamaSidecarModelsResponse,
    OllamaSidecarStatusResponse,
    OllamaSidecarTestResponse,
)

router = APIRouter(
    prefix="/api/ollama-sidecar",
    tags=["dashboard"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


@router.get("/status", response_model=OllamaSidecarStatusResponse)
async def get_status(
    context: OllamaSidecarContext = Depends(get_ollama_sidecar_context),
) -> OllamaSidecarStatusResponse:
    return await context.service.get_status()


@router.post("/test", response_model=OllamaSidecarTestResponse)
async def test_connection(
    context: OllamaSidecarContext = Depends(get_ollama_sidecar_context),
) -> OllamaSidecarTestResponse:
    return await context.service.test_connection()


@router.get("/models", response_model=OllamaSidecarModelsResponse)
async def list_models(
    context: OllamaSidecarContext = Depends(get_ollama_sidecar_context),
) -> OllamaSidecarModelsResponse:
    return await context.service.list_models()
