from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from app.core.auth.dependencies import set_dashboard_error_format, validate_dashboard_session
from app.core.clients.claude_sidecar import ClaudeSidecarClient
from app.core.clients.omniroute_sidecar import OmniRouteSidecarClient
from app.core.clients.openrouter_sidecar import OpenRouterSidecarClient
from app.core.openai.model_registry import get_model_registry, is_public_model
from app.db.session import detach_session_objects, get_background_session
from app.dependencies import DashboardContext, get_dashboard_context
from app.modules.claude_sidecar.provider_adapters import catalog_label
from app.modules.dashboard.schemas import (
    DashboardOverviewResponse,
    DashboardOverviewTimeframeKey,
    DashboardProjectionsResponse,
)
from app.modules.model_sources.catalog import source_models_to_upstream_models
from app.modules.model_sources.repository import ModelSourcesRepository
from app.modules.proxy.claude_sidecar_dispatch import load_sidecar_config
from app.modules.proxy.omniroute_sidecar_dispatch import load_omniroute_sidecar_config
from app.modules.proxy.openrouter_sidecar_dispatch import load_openrouter_sidecar_config

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["dashboard"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


@router.get("/dashboard/overview", response_model=DashboardOverviewResponse)
async def get_overview(
    timeframe: DashboardOverviewTimeframeKey = Query("7d"),
    context: DashboardContext = Depends(get_dashboard_context),
) -> DashboardOverviewResponse:
    return await context.service.get_overview(timeframe)


@router.get("/dashboard/projections", response_model=DashboardProjectionsResponse)
async def get_projections(
    context: DashboardContext = Depends(get_dashboard_context),
) -> DashboardProjectionsResponse:
    return await context.service.get_projections()


@router.get("/models")
async def list_models() -> dict:
    registry = get_model_registry()
    models_by_slug = registry.get_models_with_fallback()
    allowed_efforts = {"minimal", "low", "medium", "high", "xhigh", "max", "ultra"}

    def _normalize_effort(value: str | None) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip().lower()
        if normalized in allowed_efforts:
            return normalized
        return None

    models = [
        {
            "id": slug,
            "name": model.display_name or slug,
            "sourceOnly": False,
            "supportedReasoningEfforts": list(
                dict.fromkeys(
                    effort
                    for effort in (_normalize_effort(level.effort) for level in model.supported_reasoning_levels)
                    if effort is not None
                )
            ),
            "defaultReasoningEffort": _normalize_effort(model.default_reasoning_level),
        }
        for slug, model in models_by_slug.items()
        if is_public_model(model, None)
    ]
    seen_model_ids = {str(model["id"]) for model in models}
    sidecar_config = await load_sidecar_config()
    if sidecar_config is not None and sidecar_config.enabled:
        try:
            sidecar_models = await ClaudeSidecarClient(sidecar_config).list_models_cached()
        except Exception:
            logger.warning("failed to append Claude sidecar models to dashboard model list", exc_info=True)
            sidecar_models = []
        for sidecar_model in sidecar_models:
            if sidecar_model.id in seen_model_ids:
                continue
            seen_model_ids.add(sidecar_model.id)
            models.append(
                {
                    "id": sidecar_model.id,
                    "name": catalog_label(sidecar_model.id, sidecar_model.owned_by),
                    "sourceOnly": False,
                }
            )
    openrouter_config = await load_openrouter_sidecar_config()
    if openrouter_config is not None and openrouter_config.enabled:
        try:
            openrouter_models = await OpenRouterSidecarClient(openrouter_config).list_models_cached()
        except Exception:
            logger.warning("failed to append OpenRouter sidecar models to dashboard model list", exc_info=True)
            openrouter_models = []
        for sidecar_model in openrouter_models:
            if sidecar_model.id in seen_model_ids:
                continue
            seen_model_ids.add(sidecar_model.id)
            models.append({"id": sidecar_model.id, "name": f"OpenRouter: {sidecar_model.id}", "sourceOnly": False})
    omniroute_config = await load_omniroute_sidecar_config()
    if omniroute_config is not None and omniroute_config.enabled:
        try:
            await OmniRouteSidecarClient(omniroute_config).list_models_cached()
        except Exception:
            logger.warning("failed to refresh OmniRoute sidecar models for dashboard model list", exc_info=True)
        for model_id in omniroute_config.full_models:
            if model_id in seen_model_ids:
                continue
            seen_model_ids.add(model_id)
            models.append({"id": model_id, "name": f"OmniRoute: {model_id}", "sourceOnly": False})
    # The API-key "allowed models" picker must offer OpenAI-compatible source
    # models too, or source-scoped allowlists cannot be configured in the UI.
    async with get_background_session() as session:
        sources = await ModelSourcesRepository(session).list_enabled_sources()
        detach_session_objects(session)
    for source_model in source_models_to_upstream_models(sources):
        if source_model.slug in seen_model_ids:
            continue
        seen_model_ids.add(source_model.slug)
        models.append(
            {
                "id": source_model.slug,
                "name": source_model.display_name or source_model.slug,
                "sourceOnly": True,
            }
        )
    return {"models": models}
