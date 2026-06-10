from __future__ import annotations

from datetime import datetime, timezone

from app.core.clients.claude_sidecar import ClaudeSidecarClient, ClaudeSidecarError, ClaudeSidecarUnavailableError
from app.core.config.settings_cache import get_settings_cache
from app.modules.claude_sidecar.schemas import (
    ClaudeSidecarModelsResponse,
    ClaudeSidecarModelSummary,
    ClaudeSidecarStatus,
    ClaudeSidecarStatusResponse,
    ClaudeSidecarTestResponse,
)
from app.modules.proxy.claude_sidecar_dispatch import sidecar_config_from_settings
from app.modules.settings.repository import SettingsRepository


class ClaudeSidecarService:
    def __init__(self, settings_repository: SettingsRepository) -> None:
        self._settings_repository = settings_repository

    async def get_status(self) -> ClaudeSidecarStatusResponse:
        settings = await self._settings_repository.get_or_create()
        status, message = _classify_status(settings)
        return ClaudeSidecarStatusResponse(
            enabled=bool(settings.claude_sidecar_enabled),
            configured=settings.claude_sidecar_api_key_encrypted is not None,
            status=status,
            message=settings.claude_sidecar_last_health_message or message,
            base_url=settings.claude_sidecar_base_url,
            model_count=settings.claude_sidecar_last_model_count,
            last_checked_at=settings.claude_sidecar_last_checked_at,
        )

    async def test_connection(self) -> ClaudeSidecarTestResponse:
        settings = await self._settings_repository.get_or_create()
        static_status, static_message = _classify_static_status(settings)
        if static_status != "healthy":
            checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await self._settings_repository.update(
                claude_sidecar_last_health_status=static_status,
                claude_sidecar_last_health_message=static_message,
                claude_sidecar_last_checked_at=checked_at,
                claude_sidecar_last_model_count=None,
            )
            await get_settings_cache().invalidate()
            return ClaudeSidecarTestResponse(
                enabled=bool(settings.claude_sidecar_enabled),
                configured=settings.claude_sidecar_api_key_encrypted is not None,
                status=static_status,
                message=static_message,
                base_url=settings.claude_sidecar_base_url,
                model_count=None,
                last_checked_at=checked_at,
                models=[],
            )

        config = sidecar_config_from_settings(settings)
        client = ClaudeSidecarClient(config)
        checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            models = await client.list_models()
        except ClaudeSidecarUnavailableError as exc:
            return await self._record_test_result(
                status="unreachable",
                message=_sanitize_message(exc.message),
                checked_at=checked_at,
                models=[],
            )
        except ClaudeSidecarError as exc:
            status: ClaudeSidecarStatus = "unauthorized" if exc.status_code in {401, 403} else "error"
            return await self._record_test_result(
                status=status,
                message=_sanitize_message(exc.message),
                checked_at=checked_at,
                models=[],
            )
        return await self._record_test_result(
            status="healthy",
            message="Claude sidecar reachable",
            checked_at=checked_at,
            models=_model_summaries(models),
        )

    async def list_models(self) -> ClaudeSidecarModelsResponse:
        settings = await self._settings_repository.get_or_create()
        status, _message = _classify_static_status(settings)
        if status != "healthy":
            return ClaudeSidecarModelsResponse(models=[])
        models = await ClaudeSidecarClient(sidecar_config_from_settings(settings)).list_models_cached()
        return ClaudeSidecarModelsResponse(models=_model_summaries(models))

    async def _record_test_result(
        self,
        *,
        status: ClaudeSidecarStatus,
        message: str,
        checked_at: datetime,
        models: list[ClaudeSidecarModelSummary],
    ) -> ClaudeSidecarTestResponse:
        settings = await self._settings_repository.update(
            claude_sidecar_last_health_status=status,
            claude_sidecar_last_health_message=message,
            claude_sidecar_last_checked_at=checked_at,
            claude_sidecar_last_model_count=len(models) if status == "healthy" else None,
        )
        await get_settings_cache().invalidate()
        return ClaudeSidecarTestResponse(
            enabled=bool(settings.claude_sidecar_enabled),
            configured=settings.claude_sidecar_api_key_encrypted is not None,
            status=status,
            message=message,
            base_url=settings.claude_sidecar_base_url,
            model_count=len(models) if status == "healthy" else None,
            last_checked_at=checked_at,
            models=models,
        )


def _classify_static_status(settings) -> tuple[ClaudeSidecarStatus, str | None]:
    if not settings.claude_sidecar_enabled:
        return "disabled", "Claude sidecar is disabled"
    if settings.claude_sidecar_api_key_encrypted is None:
        return "missing_api_key", "Claude sidecar API key is not configured"
    return "healthy", None


def _classify_status(settings) -> tuple[ClaudeSidecarStatus, str | None]:
    static_status, static_message = _classify_static_status(settings)
    if static_status != "healthy":
        return static_status, static_message
    recorded_status = settings.claude_sidecar_last_health_status
    if recorded_status in {"unreachable", "unauthorized", "healthy", "error"}:
        return recorded_status, None
    return "healthy", None


def _model_summaries(models) -> list[ClaudeSidecarModelSummary]:
    return [
        ClaudeSidecarModelSummary(id=model.id, created=model.created, owned_by=model.owned_by)
        for model in models
    ]


def _sanitize_message(message: str) -> str:
    return message.replace("Bearer ", "Bearer [redacted]")
