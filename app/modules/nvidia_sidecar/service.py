from __future__ import annotations

from datetime import datetime, timezone

from app.core.clients.nvidia_sidecar import (
    NvidiaSidecarError,
    NvidiaSidecarUnavailableError,
    get_nvidia_sidecar_client,
)
from app.core.clients.orcarouter_sidecar import sanitize_orcarouter_message
from app.core.config.settings_cache import get_settings_cache
from app.modules.nvidia_sidecar.schemas import (
    NvidiaSidecarModelsResponse,
    NvidiaSidecarModelSummary,
    NvidiaSidecarStatus,
    NvidiaSidecarStatusResponse,
    NvidiaSidecarTestResponse,
)
from app.modules.proxy.nvidia_sidecar_dispatch import nvidia_sidecar_config_from_settings
from app.modules.settings.repository import SettingsRepository


class NvidiaSidecarService:
    def __init__(self, settings_repository: SettingsRepository) -> None:
        self._settings_repository = settings_repository

    async def get_status(self) -> NvidiaSidecarStatusResponse:
        settings = await self._settings_repository.get_or_create()
        status, message = _classify_status(settings)
        return NvidiaSidecarStatusResponse(
            enabled=bool(settings.nvidia_sidecar_enabled),
            configured=settings.nvidia_sidecar_api_key_encrypted is not None,
            status=status,
            message=settings.nvidia_sidecar_last_health_message or message,
            base_url=settings.nvidia_sidecar_base_url,
            model_count=settings.nvidia_sidecar_last_model_count,
            last_checked_at=settings.nvidia_sidecar_last_checked_at,
        )

    async def test_connection(self) -> NvidiaSidecarTestResponse:
        settings = await self._settings_repository.get_or_create()
        static_status, static_message = _classify_static_status(settings)
        if static_status != "healthy":
            checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await self._settings_repository.update_operational(
                nvidia_sidecar_last_health_status=static_status,
                nvidia_sidecar_last_health_message=static_message,
                nvidia_sidecar_last_checked_at=checked_at,
                nvidia_sidecar_last_model_count=None,
            )
            await get_settings_cache().invalidate()
            return NvidiaSidecarTestResponse(
                enabled=bool(settings.nvidia_sidecar_enabled),
                configured=settings.nvidia_sidecar_api_key_encrypted is not None,
                status=static_status,
                message=static_message,
                base_url=settings.nvidia_sidecar_base_url,
                model_count=None,
                last_checked_at=checked_at,
                models=[],
            )

        config = nvidia_sidecar_config_from_settings(settings)
        client = get_nvidia_sidecar_client(config)
        checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            models = await client.list_models()
        except NvidiaSidecarUnavailableError as exc:
            return await self._record_test_result(
                status="unreachable",
                message=_sanitize_message(exc.message, api_key=config.api_key),
                checked_at=checked_at,
                models=[],
            )
        except NvidiaSidecarError as exc:
            status: NvidiaSidecarStatus = "unauthorized" if exc.status_code in {401, 403} else "error"
            return await self._record_test_result(
                status=status,
                message=_sanitize_message(exc.message, api_key=config.api_key),
                checked_at=checked_at,
                models=[],
            )
        return await self._record_test_result(
            status="healthy",
            message="NVIDIA reachable",
            checked_at=checked_at,
            models=_model_summaries(models),
        )

    async def list_models(self) -> NvidiaSidecarModelsResponse:
        settings = await self._settings_repository.get_or_create()
        status, _message = _classify_static_status(settings)
        if status != "healthy":
            return NvidiaSidecarModelsResponse(models=[])
        models = await get_nvidia_sidecar_client(nvidia_sidecar_config_from_settings(settings)).list_models_cached()
        return NvidiaSidecarModelsResponse(models=_model_summaries(models))

    async def _record_test_result(
        self,
        *,
        status: NvidiaSidecarStatus,
        message: str,
        checked_at: datetime,
        models: list[NvidiaSidecarModelSummary],
    ) -> NvidiaSidecarTestResponse:
        settings = await self._settings_repository.update_operational(
            nvidia_sidecar_last_health_status=status,
            nvidia_sidecar_last_health_message=message,
            nvidia_sidecar_last_checked_at=checked_at,
            nvidia_sidecar_last_model_count=len(models) if status == "healthy" else None,
        )
        await get_settings_cache().invalidate()
        return NvidiaSidecarTestResponse(
            enabled=bool(settings.nvidia_sidecar_enabled),
            configured=settings.nvidia_sidecar_api_key_encrypted is not None,
            status=status,
            message=message,
            base_url=settings.nvidia_sidecar_base_url,
            model_count=len(models) if status == "healthy" else None,
            last_checked_at=checked_at,
            models=models,
        )


def _classify_static_status(settings) -> tuple[NvidiaSidecarStatus, str | None]:
    if not settings.nvidia_sidecar_enabled:
        return "disabled", "NVIDIA sidecar is disabled"
    if settings.nvidia_sidecar_api_key_encrypted is None:
        return "missing_api_key", "NVIDIA sidecar API key is not configured"
    return "healthy", None


def _classify_status(settings) -> tuple[NvidiaSidecarStatus, str | None]:
    static_status, static_message = _classify_static_status(settings)
    if static_status != "healthy":
        return static_status, static_message
    recorded_status = settings.nvidia_sidecar_last_health_status
    if recorded_status in {"unreachable", "unauthorized", "healthy", "error"}:
        return recorded_status, None
    return "healthy", None


def _model_summaries(models) -> list[NvidiaSidecarModelSummary]:
    return [NvidiaSidecarModelSummary(id=model.id, created=model.created, owned_by=model.owned_by) for model in models]


def _sanitize_message(message: str, *, api_key: str | None = None) -> str:
    """Strip credentials from upstream text before it is persisted and served.

    Replacing only the literal ``"Bearer "`` prefix turned an echoed
    ``Bearer nvapi-secret`` into ``Bearer [redacted]nvapi-secret``, leaving the
    key intact in ``nvidia_sidecar_last_health_message`` - which the status and
    test APIs return verbatim. The shared sanitizer replaces the whole token.
    """

    return sanitize_orcarouter_message(message, api_key=api_key)
