from __future__ import annotations

from datetime import datetime, timezone

from app.core.clients.openrouter_sidecar import (
    OpenRouterSidecarClient,
    OpenRouterSidecarError,
    OpenRouterSidecarUnavailableError,
)
from app.core.config.settings_cache import get_settings_cache
from app.modules.openrouter_sidecar.schemas import (
    OpenRouterSidecarModelSummary,
    OpenRouterSidecarModelsResponse,
    OpenRouterSidecarStatus,
    OpenRouterSidecarStatusResponse,
    OpenRouterSidecarTestResponse,
)
from app.modules.proxy.openrouter_sidecar_dispatch import openrouter_sidecar_config_from_settings
from app.modules.settings.repository import SettingsRepository


class OpenRouterSidecarService:
    def __init__(self, settings_repository: SettingsRepository) -> None:
        self._settings_repository = settings_repository

    async def get_status(self) -> OpenRouterSidecarStatusResponse:
        settings = await self._settings_repository.get_or_create()
        status, message = _classify_status(settings)
        return OpenRouterSidecarStatusResponse(
            enabled=bool(settings.openrouter_sidecar_enabled),
            configured=settings.openrouter_sidecar_api_key_encrypted is not None,
            status=status,
            message=settings.openrouter_sidecar_last_health_message or message,
            base_url=settings.openrouter_sidecar_base_url,
            model_count=settings.openrouter_sidecar_last_model_count,
            last_checked_at=settings.openrouter_sidecar_last_checked_at,
        )

    async def test_connection(self) -> OpenRouterSidecarTestResponse:
        settings = await self._settings_repository.get_or_create()
        static_status, static_message = _classify_static_status(settings)
        if static_status != "healthy":
            checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await self._settings_repository.update(
                openrouter_sidecar_last_health_status=static_status,
                openrouter_sidecar_last_health_message=static_message,
                openrouter_sidecar_last_checked_at=checked_at,
                openrouter_sidecar_last_model_count=None,
            )
            await get_settings_cache().invalidate()
            return OpenRouterSidecarTestResponse(
                enabled=bool(settings.openrouter_sidecar_enabled),
                configured=settings.openrouter_sidecar_api_key_encrypted is not None,
                status=static_status,
                message=static_message,
                base_url=settings.openrouter_sidecar_base_url,
                model_count=None,
                last_checked_at=checked_at,
                models=[],
            )

        client = OpenRouterSidecarClient(openrouter_sidecar_config_from_settings(settings))
        checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            models = await client.list_models()
        except OpenRouterSidecarUnavailableError as exc:
            return await self._record_test_result(
                status="unreachable",
                message=_sanitize_message(exc.message),
                checked_at=checked_at,
                models=[],
            )
        except OpenRouterSidecarError as exc:
            status: OpenRouterSidecarStatus = "unauthorized" if exc.status_code in {401, 403} else "error"
            return await self._record_test_result(
                status=status,
                message=_sanitize_message(exc.message),
                checked_at=checked_at,
                models=[],
            )
        return await self._record_test_result(
            status="healthy",
            message="OpenRouter sidecar reachable",
            checked_at=checked_at,
            models=_model_summaries(models),
        )

    async def list_models(self) -> OpenRouterSidecarModelsResponse:
        settings = await self._settings_repository.get_or_create()
        status, _message = _classify_static_status(settings)
        if status != "healthy":
            return OpenRouterSidecarModelsResponse(models=[])
        models = await OpenRouterSidecarClient(openrouter_sidecar_config_from_settings(settings)).list_models_cached()
        return OpenRouterSidecarModelsResponse(models=_model_summaries(models))

    async def _record_test_result(
        self,
        *,
        status: OpenRouterSidecarStatus,
        message: str,
        checked_at: datetime,
        models: list[OpenRouterSidecarModelSummary],
    ) -> OpenRouterSidecarTestResponse:
        settings = await self._settings_repository.update(
            openrouter_sidecar_last_health_status=status,
            openrouter_sidecar_last_health_message=message,
            openrouter_sidecar_last_checked_at=checked_at,
            openrouter_sidecar_last_model_count=len(models) if status == "healthy" else None,
        )
        await get_settings_cache().invalidate()
        return OpenRouterSidecarTestResponse(
            enabled=bool(settings.openrouter_sidecar_enabled),
            configured=settings.openrouter_sidecar_api_key_encrypted is not None,
            status=status,
            message=message,
            base_url=settings.openrouter_sidecar_base_url,
            model_count=len(models) if status == "healthy" else None,
            last_checked_at=checked_at,
            models=models,
        )


def _classify_static_status(settings) -> tuple[OpenRouterSidecarStatus, str | None]:
    if not settings.openrouter_sidecar_enabled:
        return "disabled", "OpenRouter sidecar is disabled"
    if settings.openrouter_sidecar_api_key_encrypted is None:
        return "missing_api_key", "OpenRouter sidecar API key is not configured"
    return "healthy", None


def _classify_status(settings) -> tuple[OpenRouterSidecarStatus, str | None]:
    static_status, static_message = _classify_static_status(settings)
    if static_status != "healthy":
        return static_status, static_message
    recorded_status = settings.openrouter_sidecar_last_health_status
    if recorded_status in {"unreachable", "unauthorized", "healthy", "error"}:
        return recorded_status, None
    return "healthy", None


def _model_summaries(models) -> list[OpenRouterSidecarModelSummary]:
    return [
        OpenRouterSidecarModelSummary(id=model.id, created=model.created, owned_by=model.owned_by)
        for model in models
    ]


def _sanitize_message(message: str) -> str:
    return message.replace("Bearer ", "Bearer [redacted]")
