from __future__ import annotations

import re
from datetime import datetime, timezone

from app.core.clients.ollama_sidecar import (
    OllamaSidecarClient,
    OllamaSidecarError,
    OllamaSidecarUnavailableError,
)
from app.core.config.settings_cache import get_settings_cache
from app.modules.ollama_sidecar.schemas import (
    OllamaSidecarModelsResponse,
    OllamaSidecarModelSummary,
    OllamaSidecarStatus,
    OllamaSidecarStatusResponse,
    OllamaSidecarTestResponse,
)
from app.modules.proxy.ollama_sidecar_dispatch import ollama_sidecar_config_from_settings
from app.modules.settings.repository import SettingsRepository


class OllamaSidecarService:
    def __init__(self, settings_repository: SettingsRepository) -> None:
        self._settings_repository = settings_repository

    async def get_status(self) -> OllamaSidecarStatusResponse:
        settings = await self._settings_repository.get_or_create()
        status, message = _classify_status(settings)
        return OllamaSidecarStatusResponse(
            enabled=bool(settings.ollama_sidecar_enabled),
            configured=settings.ollama_sidecar_api_key_encrypted is not None,
            status=status,
            message=settings.ollama_sidecar_last_health_message or message,
            base_url=settings.ollama_sidecar_base_url,
            model_count=settings.ollama_sidecar_last_model_count,
            last_checked_at=settings.ollama_sidecar_last_checked_at,
        )

    async def test_connection(self) -> OllamaSidecarTestResponse:
        settings = await self._settings_repository.get_or_create()
        static_status, static_message = _classify_static_status(settings)
        if static_status != "healthy":
            checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await self._settings_repository.update(
                ollama_sidecar_last_health_status=static_status,
                ollama_sidecar_last_health_message=static_message,
                ollama_sidecar_last_checked_at=checked_at,
                ollama_sidecar_last_model_count=None,
            )
            await get_settings_cache().invalidate()
            return OllamaSidecarTestResponse(
                enabled=bool(settings.ollama_sidecar_enabled),
                configured=settings.ollama_sidecar_api_key_encrypted is not None,
                status=static_status,
                message=static_message,
                base_url=settings.ollama_sidecar_base_url,
                model_count=None,
                last_checked_at=checked_at,
                models=[],
            )

        client = OllamaSidecarClient(ollama_sidecar_config_from_settings(settings))
        checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            models = await client.list_models()
        except OllamaSidecarUnavailableError as exc:
            return await self._record_test_result(
                status="unreachable",
                message=_sanitize_message(exc.message),
                checked_at=checked_at,
                models=[],
            )
        except OllamaSidecarError as exc:
            status: OllamaSidecarStatus = "unauthorized" if exc.status_code in {401, 403} else "error"
            return await self._record_test_result(
                status=status,
                message=_sanitize_message(exc.message),
                checked_at=checked_at,
                models=[],
            )
        return await self._record_test_result(
            status="healthy",
            message="Ollama sidecar reachable",
            checked_at=checked_at,
            models=_model_summaries(models),
        )

    async def list_models(self) -> OllamaSidecarModelsResponse:
        settings = await self._settings_repository.get_or_create()
        status, _message = _classify_static_status(settings)
        if status != "healthy":
            return OllamaSidecarModelsResponse(models=[])
        models = await OllamaSidecarClient(ollama_sidecar_config_from_settings(settings)).list_models_cached()
        return OllamaSidecarModelsResponse(models=_model_summaries(models))

    async def _record_test_result(
        self,
        *,
        status: OllamaSidecarStatus,
        message: str,
        checked_at: datetime,
        models: list[OllamaSidecarModelSummary],
    ) -> OllamaSidecarTestResponse:
        settings = await self._settings_repository.update(
            ollama_sidecar_last_health_status=status,
            ollama_sidecar_last_health_message=message,
            ollama_sidecar_last_checked_at=checked_at,
            ollama_sidecar_last_model_count=len(models) if status == "healthy" else None,
        )
        await get_settings_cache().invalidate()
        return OllamaSidecarTestResponse(
            enabled=bool(settings.ollama_sidecar_enabled),
            configured=settings.ollama_sidecar_api_key_encrypted is not None,
            status=status,
            message=message,
            base_url=settings.ollama_sidecar_base_url,
            model_count=len(models) if status == "healthy" else None,
            last_checked_at=checked_at,
            models=models,
        )


def _classify_static_status(settings) -> tuple[OllamaSidecarStatus, str | None]:
    if not settings.ollama_sidecar_enabled:
        return "disabled", "Ollama sidecar is disabled"
    if settings.ollama_sidecar_api_key_encrypted is None:
        return "missing_api_key", "Ollama sidecar API key is not configured"
    return "healthy", None


def _classify_status(settings) -> tuple[OllamaSidecarStatus, str | None]:
    static_status, static_message = _classify_static_status(settings)
    if static_status != "healthy":
        return static_status, static_message
    recorded_status = settings.ollama_sidecar_last_health_status
    if recorded_status in {"unreachable", "unauthorized", "healthy", "error"}:
        return recorded_status, None
    return "healthy", None


def _model_summaries(models) -> list[OllamaSidecarModelSummary]:
    return [OllamaSidecarModelSummary(id=model.id, created=model.created, owned_by=model.owned_by) for model in models]


_BEARER_TOKEN_RE = re.compile(r"Bearer\s+\S+", flags=re.IGNORECASE)


def _sanitize_message(message: str) -> str:
    return _BEARER_TOKEN_RE.sub("Bearer [redacted]", message)
