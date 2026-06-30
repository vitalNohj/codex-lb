from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth.dependencies import set_dashboard_error_format, validate_dashboard_session
from app.dependencies import ClaudeSidecarContext, get_claude_sidecar_context
from app.modules.claude_sidecar.schemas import (
    ClaudeSidecarAccountPriorityUpdate,
    ClaudeSidecarModelsResponse,
    ClaudeSidecarQuotaResponse,
    ClaudeSidecarRoutingResponse,
    ClaudeSidecarRoutingStrategyUpdate,
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


@router.get("/routing", response_model=ClaudeSidecarRoutingResponse)
async def get_routing(
    context: ClaudeSidecarContext = Depends(get_claude_sidecar_context),
) -> ClaudeSidecarRoutingResponse:
    return await context.service.get_routing()


@router.put("/routing/strategy", response_model=ClaudeSidecarRoutingResponse)
async def set_routing_strategy(
    body: ClaudeSidecarRoutingStrategyUpdate,
    context: ClaudeSidecarContext = Depends(get_claude_sidecar_context),
) -> ClaudeSidecarRoutingResponse:
    return await context.service.set_routing_strategy(body.strategy)


@router.put("/routing/priority", response_model=ClaudeSidecarRoutingResponse)
async def set_account_priority(
    body: ClaudeSidecarAccountPriorityUpdate,
    context: ClaudeSidecarContext = Depends(get_claude_sidecar_context),
) -> ClaudeSidecarRoutingResponse:
    return await context.service.set_account_priority(body.name, body.priority)
