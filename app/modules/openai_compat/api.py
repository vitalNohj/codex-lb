from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth.dependencies import set_dashboard_error_format, validate_dashboard_session
from app.dependencies import OpenAICompatContext, get_openai_compat_context
from app.modules.openai_compat.schemas import (
    OpenAICompatModelsResponse,
    OpenAICompatStatusResponse,
    OpenAICompatTestResponse,
)

router = APIRouter(
    prefix="/api/openai-compat",
    tags=["dashboard"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


@router.get("/{endpoint_id}/status", response_model=OpenAICompatStatusResponse)
async def get_status(
    endpoint_id: str,
    context: OpenAICompatContext = Depends(get_openai_compat_context),
) -> OpenAICompatStatusResponse:
    return await context.service.get_status(endpoint_id)


@router.post("/{endpoint_id}/test", response_model=OpenAICompatTestResponse)
async def test_connection(
    endpoint_id: str,
    context: OpenAICompatContext = Depends(get_openai_compat_context),
) -> OpenAICompatTestResponse:
    return await context.service.test_connection(endpoint_id)


@router.get("/{endpoint_id}/models", response_model=OpenAICompatModelsResponse)
async def list_models(
    endpoint_id: str,
    context: OpenAICompatContext = Depends(get_openai_compat_context),
) -> OpenAICompatModelsResponse:
    return await context.service.list_models(endpoint_id)
