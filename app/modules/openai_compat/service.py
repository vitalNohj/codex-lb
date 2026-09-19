from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException

from app.core.clients.openai_compat_sidecar import (
    OpenAICompatSidecarClient,
    OpenAICompatSidecarError,
    OpenAICompatSidecarUnavailableError,
)
from app.core.config.settings_cache import get_settings_cache
from app.modules.openai_compat.endpoints import (
    dump_openai_compat_endpoints,
    parse_openai_compat_endpoints,
    patch_endpoint_health,
)
from app.modules.openai_compat.schemas import (
    OpenAICompatModelsResponse,
    OpenAICompatModelSummary,
    OpenAICompatStatus,
    OpenAICompatStatusResponse,
    OpenAICompatTestResponse,
)
from app.modules.proxy.openai_compat_dispatch import (
    openai_compat_config_by_provider,
    openai_compat_configs_from_settings,
)
from app.modules.settings.repository import SettingsRepository


class OpenAICompatService:
    def __init__(self, settings_repository: SettingsRepository) -> None:
        self._settings_repository = settings_repository

    async def get_status(self, endpoint_id: str) -> OpenAICompatStatusResponse:
        settings = await self._settings_repository.get_or_create()
        endpoint = _require_endpoint(settings.openai_compat_endpoints_json, endpoint_id)
        status, message = _classify_status(endpoint.enabled, endpoint.last_health_status)
        return OpenAICompatStatusResponse(
            id=endpoint.id,
            name=endpoint.name,
            enabled=endpoint.enabled,
            configured=True,
            status=status,
            message=endpoint.last_health_message or message,
            base_url=endpoint.base_url,
            model_count=endpoint.last_model_count,
            last_checked_at=endpoint.last_checked_at,
        )

    async def test_connection(self, endpoint_id: str) -> OpenAICompatTestResponse:
        settings = await self._settings_repository.get_or_create()
        endpoint = _require_endpoint(settings.openai_compat_endpoints_json, endpoint_id)
        checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        if not endpoint.enabled:
            return await self._record_test_result(
                endpoint_id,
                status="disabled",
                message="OpenAI-compat endpoint is disabled",
                checked_at=checked_at,
                models=[],
            )

        config = openai_compat_config_by_provider(
            openai_compat_configs_from_settings(settings),
            endpoint.provider_id,
        )
        if config is None:
            raise HTTPException(status_code=404, detail="OpenAI-compat endpoint not found")
        client = OpenAICompatSidecarClient(config)
        try:
            models = await client.list_models()
        except OpenAICompatSidecarUnavailableError as exc:
            return await self._record_test_result(
                endpoint_id,
                status="unreachable",
                message=_sanitize_message(exc.message),
                checked_at=checked_at,
                models=[],
            )
        except OpenAICompatSidecarError as exc:
            status: OpenAICompatStatus = "unauthorized" if exc.status_code in {401, 403} else "error"
            return await self._record_test_result(
                endpoint_id,
                status=status,
                message=_sanitize_message(exc.message),
                checked_at=checked_at,
                models=[],
            )
        return await self._record_test_result(
            endpoint_id,
            status="healthy",
            message=f"{endpoint.name} reachable",
            checked_at=checked_at,
            models=_model_summaries(models),
        )

    async def list_models(self, endpoint_id: str) -> OpenAICompatModelsResponse:
        settings = await self._settings_repository.get_or_create()
        endpoint = _require_endpoint(settings.openai_compat_endpoints_json, endpoint_id)
        if not endpoint.enabled:
            return OpenAICompatModelsResponse(models=[])
        config = openai_compat_config_by_provider(
            openai_compat_configs_from_settings(settings),
            endpoint.provider_id,
        )
        if config is None:
            return OpenAICompatModelsResponse(models=[])
        models = await OpenAICompatSidecarClient(config).list_models_cached()
        return OpenAICompatModelsResponse(models=_model_summaries(models))

    async def _record_test_result(
        self,
        endpoint_id: str,
        *,
        status: OpenAICompatStatus,
        message: str,
        checked_at: datetime,
        models: list[OpenAICompatModelSummary],
    ) -> OpenAICompatTestResponse:
        settings = await self._settings_repository.get_or_create()
        patched = patch_endpoint_health(
            parse_openai_compat_endpoints(settings.openai_compat_endpoints_json),
            endpoint_id,
            last_health_status=status,
            last_health_message=message,
            last_checked_at=checked_at,
            last_model_count=len(models) if status == "healthy" else None,
        )
        settings = await self._settings_repository.update_operational(
            openai_compat_endpoints_json=dump_openai_compat_endpoints(patched),
        )
        await get_settings_cache().invalidate()
        endpoint = _require_endpoint(settings.openai_compat_endpoints_json, endpoint_id)
        return OpenAICompatTestResponse(
            id=endpoint.id,
            name=endpoint.name,
            enabled=endpoint.enabled,
            configured=True,
            status=status,
            message=message,
            base_url=endpoint.base_url,
            model_count=len(models) if status == "healthy" else None,
            last_checked_at=checked_at,
            models=models,
        )


def _require_endpoint(raw: str | None, endpoint_id: str):
    for endpoint in parse_openai_compat_endpoints(raw):
        if endpoint.id == endpoint_id:
            return endpoint
    raise HTTPException(status_code=404, detail="OpenAI-compat endpoint not found")


def _classify_status(enabled: bool, recorded_status: str | None) -> tuple[OpenAICompatStatus, str | None]:
    if not enabled:
        return "disabled", "OpenAI-compat endpoint is disabled"
    if recorded_status in {"unreachable", "unauthorized", "healthy", "error"}:
        return recorded_status, None
    return "healthy", None


def _model_summaries(models) -> list[OpenAICompatModelSummary]:
    return [
        OpenAICompatModelSummary(id=model.id, created=model.created, owned_by=model.owned_by)
        for model in models
    ]


def _sanitize_message(message: str) -> str:
    return message.replace("Bearer ", "Bearer [redacted]")
