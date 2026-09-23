from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException

from app.core.clients.openai_compat_sidecar import (
    OpenAICompatSidecarError,
    OpenAICompatSidecarUnavailableError,
    get_openai_compat_sidecar_client,
)
from app.core.clients.orcarouter_sidecar import sanitize_orcarouter_message
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

# Bounded like the discovery pin retry: a lost compare-and-set means another
# writer won, and re-patching on top of the winner is cheap, but the loop must
# terminate. On exhaustion the last read is returned rather than raising: a
# health result is observability, and failing an operator's Test button because a
# concurrent save kept winning would be a worse outcome than a missed status.
_RECORD_HEALTH_MAX_ATTEMPTS = 3


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
        client = get_openai_compat_sidecar_client(config)
        try:
            models = await client.list_models()
        except OpenAICompatSidecarUnavailableError as exc:
            return await self._record_test_result(
                endpoint_id,
                status="unreachable",
                message=_sanitize_message(exc.message, api_key=config.api_key),
                checked_at=checked_at,
                models=[],
            )
        except OpenAICompatSidecarError as exc:
            status: OpenAICompatStatus = "unauthorized" if exc.status_code in {401, 403} else "error"
            return await self._record_test_result(
                endpoint_id,
                status=status,
                message=_sanitize_message(exc.message, api_key=config.api_key),
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
        models = await get_openai_compat_sidecar_client(config).list_models_cached()
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
        """Persist one endpoint's health under the settings version CAS.

        One JSON column holds every endpoint's *configuration* as well as its
        health, so writing the whole blob back from a stale read is a lost
        update, not a stale-display nuisance: a second endpoint test, or an
        operator save landing in between, is reverted wholesale. Two operator
        actions genuinely can overlap here - each dashboard endpoint card has its
        own Test button and they are independent requests.

        So the write goes through ``update_operational_json_column`` (the same
        CAS path free-model discovery uses for its shared JSON column) and, on
        conflict, re-reads and re-patches on top of the winner instead of
        overwriting it. Only this endpoint's health fields are re-applied, so the
        other writer's endpoint edits survive.
        """

        last_model_count = len(models) if status == "healthy" else None
        settings = await self._settings_repository.get_or_create()
        for _attempt in range(_RECORD_HEALTH_MAX_ATTEMPTS):
            current = settings.openai_compat_endpoints_json
            patched = patch_endpoint_health(
                parse_openai_compat_endpoints(current),
                endpoint_id,
                last_health_status=status,
                last_health_message=message,
                last_checked_at=checked_at,
                last_model_count=last_model_count,
            )
            written = await self._settings_repository.update_operational_json_column_if_unchanged(
                "openai_compat_endpoints_json",
                expected=current,
                value=dump_openai_compat_endpoints(patched),
            )
            if written:
                break
            # Another writer changed the blob between this read and the write.
            # Their edit stands: re-read and re-apply only this endpoint's health
            # fields on top of it, rather than overwriting it with a stale copy.
            settings = await self._settings_repository.get_fresh()
        await get_settings_cache().invalidate()
        settings = await self._settings_repository.get_fresh()
        endpoint = _require_endpoint(settings.openai_compat_endpoints_json, endpoint_id)
        return OpenAICompatTestResponse(
            id=endpoint.id,
            name=endpoint.name,
            enabled=endpoint.enabled,
            configured=True,
            status=status,
            message=message,
            base_url=endpoint.base_url,
            model_count=last_model_count,
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
    return [OpenAICompatModelSummary(id=model.id, created=model.created, owned_by=model.owned_by) for model in models]


def _sanitize_message(message: str, *, api_key: str | None = None) -> str:
    """Strip credentials from upstream text before it is persisted and served.

    The previous implementation replaced only the literal ``"Bearer "`` prefix,
    so an upstream echoing ``Bearer sk-secret`` produced
    ``Bearer [redacted]sk-secret`` - the key itself survived intact into
    ``last_health_message``, which the status and test APIs return verbatim.

    Delegates to the project's existing credential-aware sanitizer rather than
    growing a second dialect: it replaces the whole bearer token, also matches a
    bare echo of the configured key whatever its shape, and is already the
    contract free-model discovery reuses for non-OrcaRouter providers (see
    ``app/modules/free_model_discovery/probe.redact_provider_text``).
    """

    return sanitize_orcarouter_message(message, api_key=api_key)
