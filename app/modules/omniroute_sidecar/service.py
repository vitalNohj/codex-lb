from __future__ import annotations

from datetime import datetime, timezone

from app.core.clients.omniroute_sidecar import (
    OmniRouteSidecarClient,
    OmniRouteSidecarError,
    OmniRouteSidecarUnavailableError,
)
from app.core.config.settings_cache import get_settings_cache
from app.modules.omniroute_sidecar.schemas import (
    OmniRouteSidecarModelsResponse,
    OmniRouteSidecarModelSummary,
    OmniRouteSidecarStatus,
    OmniRouteSidecarStatusResponse,
    OmniRouteSidecarTestResponse,
)
from app.modules.proxy.omniroute_sidecar_dispatch import omniroute_sidecar_config_from_settings
from app.modules.settings.repository import SettingsRepository


class OmniRouteSidecarService:
    def __init__(self, settings_repository: SettingsRepository) -> None:
        self._settings_repository = settings_repository

    async def get_status(self) -> OmniRouteSidecarStatusResponse:
        settings = await self._settings_repository.get_or_create()
        status, message = _classify_status(settings)
        return OmniRouteSidecarStatusResponse(
            enabled=bool(settings.omniroute_sidecar_enabled),
            configured=settings.omniroute_sidecar_api_key_encrypted is not None,
            status=status,
            message=settings.omniroute_sidecar_last_health_message or message,
            base_url=settings.omniroute_sidecar_base_url,
            model_count=settings.omniroute_sidecar_last_model_count,
            last_checked_at=settings.omniroute_sidecar_last_checked_at,
        )

    async def test_connection(self) -> OmniRouteSidecarTestResponse:
        settings = await self._settings_repository.get_or_create()
        static_status, static_message = _classify_static_status(settings)
        if static_status != "healthy":
            checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await self._settings_repository.update(
                omniroute_sidecar_last_health_status=static_status,
                omniroute_sidecar_last_health_message=static_message,
                omniroute_sidecar_last_checked_at=checked_at,
                omniroute_sidecar_last_model_count=None,
            )
            await get_settings_cache().invalidate()
            return OmniRouteSidecarTestResponse(
                enabled=bool(settings.omniroute_sidecar_enabled),
                configured=settings.omniroute_sidecar_api_key_encrypted is not None,
                status=static_status,
                message=static_message,
                base_url=settings.omniroute_sidecar_base_url,
                model_count=None,
                last_checked_at=checked_at,
                models=[],
            )

        client = OmniRouteSidecarClient(omniroute_sidecar_config_from_settings(settings))
        checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            models = await client.list_models()
        except OmniRouteSidecarUnavailableError as exc:
            return await self._record_test_result(
                status="unreachable",
                message=_sanitize_message(exc.message),
                checked_at=checked_at,
                models=[],
            )
        except OmniRouteSidecarError as exc:
            status: OmniRouteSidecarStatus = "unauthorized" if exc.status_code in {401, 403} else "error"
            return await self._record_test_result(
                status=status,
                message=_sanitize_message(exc.message),
                checked_at=checked_at,
                models=[],
            )
        return await self._record_test_result(
            status="healthy",
            message="OmniRoute sidecar reachable",
            checked_at=checked_at,
            models=_model_summaries(models),
        )

    async def list_models(self) -> OmniRouteSidecarModelsResponse:
        settings = await self._settings_repository.get_or_create()
        status, _message = _classify_static_status(settings)
        if status != "healthy":
            return OmniRouteSidecarModelsResponse(models=[])
        models = await OmniRouteSidecarClient(omniroute_sidecar_config_from_settings(settings)).list_models_cached()
        return OmniRouteSidecarModelsResponse(models=_model_summaries(models))

    async def _record_test_result(
        self,
        *,
        status: OmniRouteSidecarStatus,
        message: str,
        checked_at: datetime,
        models: list[OmniRouteSidecarModelSummary],
    ) -> OmniRouteSidecarTestResponse:
        settings = await self._settings_repository.update(
            omniroute_sidecar_last_health_status=status,
            omniroute_sidecar_last_health_message=message,
            omniroute_sidecar_last_checked_at=checked_at,
            omniroute_sidecar_last_model_count=len(models) if status == "healthy" else None,
        )
        await get_settings_cache().invalidate()
        return OmniRouteSidecarTestResponse(
            enabled=bool(settings.omniroute_sidecar_enabled),
            configured=settings.omniroute_sidecar_api_key_encrypted is not None,
            status=status,
            message=message,
            base_url=settings.omniroute_sidecar_base_url,
            model_count=len(models) if status == "healthy" else None,
            last_checked_at=checked_at,
            models=models,
        )


def _classify_static_status(settings) -> tuple[OmniRouteSidecarStatus, str | None]:
    if not settings.omniroute_sidecar_enabled:
        return "disabled", "OmniRoute sidecar is disabled"
    if settings.omniroute_sidecar_api_key_encrypted is None:
        return "missing_api_key", "OmniRoute sidecar API key is not configured"
    return "healthy", None


def _classify_status(settings) -> tuple[OmniRouteSidecarStatus, str | None]:
    static_status, static_message = _classify_static_status(settings)
    if static_status != "healthy":
        return static_status, static_message
    recorded_status = settings.omniroute_sidecar_last_health_status
    if recorded_status in {"unreachable", "unauthorized", "healthy", "error"}:
        return recorded_status, None
    return "healthy", None


def _model_summaries(models) -> list[OmniRouteSidecarModelSummary]:
    return [
        OmniRouteSidecarModelSummary(id=model.id, created=model.created, owned_by=model.owned_by) for model in models
    ]


def _sanitize_message(message: str) -> str:
    return message.replace("Bearer ", "Bearer [redacted]")
