from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from app.core.clients.claude_sidecar import SidecarModel
from app.core.clients.opencode_go_sidecar import (
    OpenCodeGoSidecarError,
    OpenCodeGoSidecarUnavailableError,
    get_opencode_go_sidecar_client,
    sanitize_opencode_go_message,
)
from app.core.config.settings_cache import get_settings_cache
from app.db.models import DashboardSettings
from app.modules.opencode_go_sidecar.schemas import (
    OpenCodeGoSidecarModelsResponse,
    OpenCodeGoSidecarModelSummary,
    OpenCodeGoSidecarStatus,
    OpenCodeGoSidecarStatusResponse,
    OpenCodeGoSidecarTestResponse,
)
from app.modules.proxy.opencode_go_models import (
    is_opencode_go_model_supported,
    opencode_go_model_protocol,
)
from app.modules.proxy.opencode_go_sidecar_dispatch import opencode_go_sidecar_config_from_settings
from app.modules.settings.repository import SettingsRepository


class OpenCodeGoSidecarService:
    def __init__(self, settings_repository: SettingsRepository) -> None:
        self._settings_repository = settings_repository

    async def get_status(self) -> OpenCodeGoSidecarStatusResponse:
        settings = await self._settings_repository.get_or_create()
        status, message = _classify_status(settings)
        return OpenCodeGoSidecarStatusResponse(
            enabled=bool(settings.opencode_go_sidecar_enabled),
            configured=settings.opencode_go_sidecar_api_key_encrypted is not None,
            status=status,
            message=settings.opencode_go_sidecar_last_health_message or message,
            base_url=settings.opencode_go_sidecar_base_url,
            model_count=settings.opencode_go_sidecar_last_model_count,
            last_checked_at=settings.opencode_go_sidecar_last_checked_at,
        )

    async def test_connection(self) -> OpenCodeGoSidecarTestResponse:
        settings = await self._settings_repository.get_or_create()
        static_status, static_message = _classify_static_status(settings)
        if static_status != "healthy":
            checked_at = _now()
            await self._settings_repository.update_operational(
                opencode_go_sidecar_last_health_status=static_status,
                opencode_go_sidecar_last_health_message=static_message,
                opencode_go_sidecar_last_checked_at=checked_at,
                opencode_go_sidecar_last_model_count=None,
            )
            await get_settings_cache().invalidate()
            return OpenCodeGoSidecarTestResponse(
                enabled=bool(settings.opencode_go_sidecar_enabled),
                configured=settings.opencode_go_sidecar_api_key_encrypted is not None,
                status=static_status,
                message=static_message,
                base_url=settings.opencode_go_sidecar_base_url,
                model_count=None,
                last_checked_at=checked_at,
                models=[],
            )

        config = opencode_go_sidecar_config_from_settings(settings)
        client = get_opencode_go_sidecar_client(config)
        checked_at = _now()
        try:
            models = await client.list_models()
        except OpenCodeGoSidecarUnavailableError as exc:
            return await self._record_test_result(
                status="unreachable",
                message=sanitize_opencode_go_message(exc.message, api_key=config.api_key),
                checked_at=checked_at,
                models=[],
            )
        except OpenCodeGoSidecarError as exc:
            status: OpenCodeGoSidecarStatus = "unauthorized" if exc.status_code in {401, 403} else "error"
            return await self._record_test_result(
                status=status,
                message=sanitize_opencode_go_message(exc.message, api_key=config.api_key),
                checked_at=checked_at,
                models=[],
            )
        return await self._record_test_result(
            status="healthy",
            message="OpenCode Go reachable",
            checked_at=checked_at,
            models=_model_summaries(models),
        )

    async def list_models(self) -> OpenCodeGoSidecarModelsResponse:
        settings = await self._settings_repository.get_or_create()
        status, _message = _classify_static_status(settings)
        if status != "healthy":
            # Disabled or unconfigured: answer without any upstream call, so an
            # operator merely opening the Settings page cannot originate traffic
            # to a subscription they have not turned on.
            return OpenCodeGoSidecarModelsResponse(models=[])
        # Config-keyed client so ``models_cache_ttl_seconds`` actually spans
        # requests; an inline client resets the TTL state on every call.
        client = get_opencode_go_sidecar_client(opencode_go_sidecar_config_from_settings(settings))
        models = await client.list_models_cached()
        return OpenCodeGoSidecarModelsResponse(models=_model_summaries(models))

    async def _record_test_result(
        self,
        *,
        status: OpenCodeGoSidecarStatus,
        message: str,
        checked_at: datetime,
        models: list[OpenCodeGoSidecarModelSummary],
    ) -> OpenCodeGoSidecarTestResponse:
        # The recorded count is the number of models this build can actually
        # dispatch, not the raw listing length. Recording the listing length
        # would tell an operator "27 models available" when 12 of them are on
        # endpoints we do not speak.
        supported_count = sum(1 for model in models if model.supported) if status == "healthy" else None
        settings = await self._settings_repository.update_operational(
            opencode_go_sidecar_last_health_status=status,
            opencode_go_sidecar_last_health_message=message,
            opencode_go_sidecar_last_checked_at=checked_at,
            opencode_go_sidecar_last_model_count=supported_count,
        )
        await get_settings_cache().invalidate()
        return OpenCodeGoSidecarTestResponse(
            enabled=bool(settings.opencode_go_sidecar_enabled),
            configured=settings.opencode_go_sidecar_api_key_encrypted is not None,
            status=status,
            message=message,
            base_url=settings.opencode_go_sidecar_base_url,
            model_count=supported_count,
            last_checked_at=checked_at,
            models=models,
        )


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _classify_static_status(settings: DashboardSettings) -> tuple[OpenCodeGoSidecarStatus, str | None]:
    if not settings.opencode_go_sidecar_enabled:
        return "disabled", "OpenCode Go is disabled"
    if settings.opencode_go_sidecar_api_key_encrypted is None:
        return "missing_api_key", "OpenCode Go API key is not configured"
    return "healthy", None


def _classify_status(settings: DashboardSettings) -> tuple[OpenCodeGoSidecarStatus, str | None]:
    static_status, static_message = _classify_static_status(settings)
    if static_status != "healthy":
        return static_status, static_message
    recorded_status = settings.opencode_go_sidecar_last_health_status
    if recorded_status in {"unreachable", "unauthorized", "healthy", "error"}:
        return recorded_status, None
    return "healthy", None


def _model_summaries(models: Sequence[SidecarModel]) -> list[OpenCodeGoSidecarModelSummary]:
    return [
        OpenCodeGoSidecarModelSummary(
            id=model.id,
            created=model.created,
            owned_by=model.owned_by,
            protocol=opencode_go_model_protocol(model.id).value,
            supported=is_opencode_go_model_supported(model.id),
        )
        for model in models
    ]
