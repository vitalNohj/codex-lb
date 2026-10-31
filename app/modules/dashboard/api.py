from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.core.auth.dashboard_access import DashboardPrincipal, Permission
from app.core.auth.dependencies import (
    require_dashboard_permission,
    set_dashboard_error_format,
    validate_dashboard_session,
)
from app.core.clients.claude_sidecar import ClaudeSidecarClient, SidecarModel
from app.core.clients.omniroute_sidecar import OmniRouteSidecarClient
from app.core.clients.openai_compat_sidecar import get_openai_compat_sidecar_client
from app.core.clients.opencode_go_sidecar import get_opencode_go_sidecar_client
from app.core.clients.openrouter_sidecar import OpenRouterSidecarClient
from app.core.clients.orcarouter_sidecar import get_orcarouter_sidecar_client
from app.core.openai.model_registry import get_model_registry, is_public_model
from app.db.session import detach_session_objects, get_background_session
from app.dependencies import DashboardContext, get_dashboard_context
from app.modules.dashboard.schemas import (
    DashboardOverviewResponse,
    DashboardOverviewTimeframeKey,
    DashboardProjectionsResponse,
    DashboardSyncStatusResponse,
)
from app.modules.model_sources.catalog import source_models_to_upstream_models
from app.modules.model_sources.repository import ModelSourcesRepository
from app.modules.proxy.claude_sidecar_dispatch import load_sidecar_config
from app.modules.proxy.cliproxy_picker_models import cliproxy_picker_model_ids, subscription_picker_model_ids
from app.modules.proxy.omniroute_sidecar_dispatch import load_omniroute_sidecar_config
from app.modules.proxy.openai_compat_dispatch import load_openai_compat_configs
from app.modules.proxy.opencode_go_models import is_opencode_go_model_supported
from app.modules.proxy.opencode_go_sidecar_dispatch import (
    load_opencode_go_sidecar_config,
    opencode_go_is_usable,
)
from app.modules.proxy.openrouter_sidecar_dispatch import load_openrouter_sidecar_config, openrouter_is_usable
from app.modules.proxy.orcarouter_sidecar_dispatch import load_orcarouter_sidecar_config, orcarouter_is_usable

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["dashboard"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


@router.get(
    "/dashboard/overview",
    response_model=DashboardOverviewResponse,
    dependencies=[Depends(require_dashboard_permission(Permission.ACCOUNTS_READ))],
)
async def get_overview(
    timeframe: DashboardOverviewTimeframeKey = Query("7d"),
    principal: DashboardPrincipal = Depends(validate_dashboard_session),
    context: DashboardContext = Depends(get_dashboard_context),
) -> DashboardOverviewResponse:
    return await context.service.get_overview(
        timeframe,
        redact_identity=not principal.has(Permission.ACCOUNTS_WRITE),
    )


@router.get(
    "/dashboard/sync-status",
    response_model=DashboardSyncStatusResponse,
    dependencies=[Depends(require_dashboard_permission(Permission.ACCOUNTS_READ))],
)
async def get_sync_status(
    context: DashboardContext = Depends(get_dashboard_context),
) -> DashboardSyncStatusResponse:
    return await context.service.get_sync_status()


@router.get(
    "/dashboard/projections",
    response_model=DashboardProjectionsResponse,
    dependencies=[Depends(require_dashboard_permission(Permission.ACCOUNTS_READ))],
)
async def get_projections(
    context: DashboardContext = Depends(get_dashboard_context),
) -> DashboardProjectionsResponse:
    return await context.service.get_projections()


@router.get("/models", dependencies=[Depends(require_dashboard_permission(Permission.DASHBOARD_READ))])
async def list_models(
    scope: Literal["subscriptions"] | None = Query(default=None),
) -> dict:
    """Dashboard model catalog.

    ``scope=subscriptions`` is the API-key limit-rules picker: Codex registry
    models plus CLIProxyAPI models from Claude and xAI subscription logins.
    The default list also offers the other configured providers.
    """
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
        sidecar_client = ClaudeSidecarClient(sidecar_config)
        # Raw ``/v1/models`` ids include per-account ``lb<hash>/`` aliases.
        # Pickers store the client model, which is what logs and limits compare.
        # The subscription scope reads Claude and xAI auth-file catalogs instead,
        # so a Codex login listed by the shared endpoint cannot enter the picker.
        if scope == "subscriptions":
            picker_ids = await subscription_picker_model_ids(sidecar_client, sidecar_config)
        else:
            try:
                sidecar_models = await sidecar_client.list_models_cached()
            except Exception:
                logger.warning("failed to append Claude sidecar models to dashboard model list", exc_info=True)
                sidecar_models = []
            picker_ids = cliproxy_picker_model_ids(
                tuple(sidecar_model.id for sidecar_model in sidecar_models),
                prefixes=sidecar_config.prefixes,
                full_models=sidecar_config.full_models,
            )
        for model_id in picker_ids:
            if model_id in seen_model_ids:
                continue
            seen_model_ids.add(model_id)
            models.append({"id": model_id, "name": f"CLIProxyAPI: {model_id}", "sourceOnly": False})
    if scope == "subscriptions":
        return {"models": models}
    openrouter_config = await load_openrouter_sidecar_config()
    # Usable credential required, as for OpenCode Go: the picker must not poll
    # an upstream the deployment has no key for, nor offer models it would refuse.
    if openrouter_is_usable(openrouter_config):
        assert openrouter_config is not None
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
    openai_compat_configs = await load_openai_compat_configs()
    # Refresh the enabled endpoints concurrently, for the same reason
    # ``_build_models_response_body`` does: each endpoint carries its own
    # ``request_timeout_seconds`` (600 s by default) and there can be up to
    # ``OPENAI_COMPAT_MAX_ENDPOINTS`` of them, so a serial loop on a cold cache
    # stacked every endpoint's timeout and stalled the dashboard model picker.
    # ``return_exceptions=True`` preserves the per-endpoint isolation the
    # per-endpoint ``try`` gave: one unreachable endpoint must not drop the
    # others from the picker. Results stay positionally aligned with
    # ``enabled_openai_compat_configs``, so the listed order is unchanged.
    enabled_openai_compat_configs = [config for config in openai_compat_configs if config.enabled]
    openai_compat_results = await asyncio.gather(
        *(get_openai_compat_sidecar_client(config).list_models_cached() for config in enabled_openai_compat_configs),
        return_exceptions=True,
    )
    for openai_compat_config, openai_compat_result in zip(
        enabled_openai_compat_configs, openai_compat_results, strict=True
    ):
        if isinstance(openai_compat_result, BaseException):
            if isinstance(openai_compat_result, asyncio.CancelledError):
                # The request itself is going away, not this endpoint failing.
                raise openai_compat_result
            logger.warning(
                "failed to append OpenAI-compat models to dashboard model list endpoint_id=%s",
                openai_compat_config.endpoint_id,
                exc_info=openai_compat_result,
            )
            openai_compat_models: list[SidecarModel] = []
        else:
            openai_compat_models = openai_compat_result
        for sidecar_model in openai_compat_models:
            if sidecar_model.id in seen_model_ids:
                continue
            seen_model_ids.add(sidecar_model.id)
            models.append(
                {
                    "id": sidecar_model.id,
                    "name": f"{openai_compat_config.name}: {sidecar_model.id}",
                    "sourceOnly": False,
                }
            )
    orcarouter_config = await load_orcarouter_sidecar_config()
    if orcarouter_is_usable(orcarouter_config):
        assert orcarouter_config is not None
        try:
            # Config-keyed client so ``models_cache_ttl_seconds`` spans requests;
            # an inline client discards the TTL state on every model-picker load.
            orcarouter_models = await get_orcarouter_sidecar_client(orcarouter_config).list_models_cached()
        except Exception:
            logger.warning("failed to append OrcaRouter models to dashboard model list", exc_info=True)
            orcarouter_models = []
        for sidecar_model in orcarouter_models:
            if sidecar_model.id in seen_model_ids:
                continue
            seen_model_ids.add(sidecar_model.id)
            models.append({"id": sidecar_model.id, "name": f"OrcaRouter: {sidecar_model.id}", "sourceOnly": False})
    opencode_go_config = await load_opencode_go_sidecar_config()
    # Usable credential required: opening the dashboard model picker must not
    # poll a subscription the deployment has no key for.
    if opencode_go_is_usable(opencode_go_config):
        try:
            opencode_go_models = await get_opencode_go_sidecar_client(opencode_go_config).list_models_cached()
        except Exception:
            logger.warning("failed to append OpenCode Go models to dashboard model list", exc_info=True)
            opencode_go_models = []
        for sidecar_model in opencode_go_models:
            # This picker feeds aliases and API-key model allowances, so an
            # entry here is an offer to route. Models Go serves on /messages or
            # /responses are not routable by this build and are left out rather
            # than offered and then rejected at dispatch time.
            if not is_opencode_go_model_supported(sidecar_model.id):
                continue
            if sidecar_model.id in seen_model_ids:
                continue
            seen_model_ids.add(sidecar_model.id)
            models.append({"id": sidecar_model.id, "name": f"OpenCode Go: {sidecar_model.id}", "sourceOnly": False})
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
