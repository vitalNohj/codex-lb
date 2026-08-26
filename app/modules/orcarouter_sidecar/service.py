from __future__ import annotations

import re
from datetime import datetime, timezone

from app.core.clients.orcarouter_sidecar import (
    OrcaRouterSidecarClient,
    OrcaRouterSidecarError,
    OrcaRouterSidecarUnavailableError,
)
from app.core.config.settings_cache import get_settings_cache
from app.modules.orcarouter_sidecar.schemas import (
    OrcaRouterSidecarModelsResponse,
    OrcaRouterSidecarModelSummary,
    OrcaRouterSidecarStatus,
    OrcaRouterSidecarStatusResponse,
    OrcaRouterSidecarTestResponse,
)
from app.modules.proxy.orcarouter_sidecar_dispatch import orcarouter_sidecar_config_from_settings
from app.modules.settings.repository import SettingsRepository


class OrcaRouterSidecarService:
    def __init__(self, settings_repository: SettingsRepository) -> None:
        self._settings_repository = settings_repository

    async def get_status(self) -> OrcaRouterSidecarStatusResponse:
        settings = await self._settings_repository.get_or_create()
        status, message = _classify_status(settings)
        return OrcaRouterSidecarStatusResponse(
            enabled=bool(settings.orcarouter_sidecar_enabled),
            configured=settings.orcarouter_sidecar_api_key_encrypted is not None,
            status=status,
            message=settings.orcarouter_sidecar_last_health_message or message,
            base_url=settings.orcarouter_sidecar_base_url,
            model_count=settings.orcarouter_sidecar_last_model_count,
            last_checked_at=settings.orcarouter_sidecar_last_checked_at,
        )

    async def test_connection(self) -> OrcaRouterSidecarTestResponse:
        settings = await self._settings_repository.get_or_create()
        static_status, static_message = _classify_static_status(settings)
        if static_status != "healthy":
            checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await self._settings_repository.update(
                orcarouter_sidecar_last_health_status=static_status,
                orcarouter_sidecar_last_health_message=static_message,
                orcarouter_sidecar_last_checked_at=checked_at,
                orcarouter_sidecar_last_model_count=None,
            )
            await get_settings_cache().invalidate()
            return OrcaRouterSidecarTestResponse(
                enabled=bool(settings.orcarouter_sidecar_enabled),
                configured=settings.orcarouter_sidecar_api_key_encrypted is not None,
                status=static_status,
                message=static_message,
                base_url=settings.orcarouter_sidecar_base_url,
                model_count=None,
                last_checked_at=checked_at,
                models=[],
            )

        config = orcarouter_sidecar_config_from_settings(settings)
        client = OrcaRouterSidecarClient(config)
        checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            models = await client.list_models()
        except OrcaRouterSidecarUnavailableError as exc:
            return await self._record_test_result(
                status="unreachable",
                message=_sanitize_message(exc.message, api_key=config.api_key),
                checked_at=checked_at,
                models=[],
            )
        except OrcaRouterSidecarError as exc:
            status: OrcaRouterSidecarStatus = "unauthorized" if exc.status_code in {401, 403} else "error"
            return await self._record_test_result(
                status=status,
                message=_sanitize_message(exc.message, api_key=config.api_key),
                checked_at=checked_at,
                models=[],
            )
        return await self._record_test_result(
            status="healthy",
            message="OrcaRouter sidecar reachable",
            checked_at=checked_at,
            models=_model_summaries(models),
        )

    async def list_models(self) -> OrcaRouterSidecarModelsResponse:
        settings = await self._settings_repository.get_or_create()
        status, _message = _classify_static_status(settings)
        if status != "healthy":
            return OrcaRouterSidecarModelsResponse(models=[])
        models = await OrcaRouterSidecarClient(orcarouter_sidecar_config_from_settings(settings)).list_models_cached()
        return OrcaRouterSidecarModelsResponse(models=_model_summaries(models))

    async def _record_test_result(
        self,
        *,
        status: OrcaRouterSidecarStatus,
        message: str,
        checked_at: datetime,
        models: list[OrcaRouterSidecarModelSummary],
    ) -> OrcaRouterSidecarTestResponse:
        settings = await self._settings_repository.update(
            orcarouter_sidecar_last_health_status=status,
            orcarouter_sidecar_last_health_message=message,
            orcarouter_sidecar_last_checked_at=checked_at,
            orcarouter_sidecar_last_model_count=len(models) if status == "healthy" else None,
        )
        await get_settings_cache().invalidate()
        return OrcaRouterSidecarTestResponse(
            enabled=bool(settings.orcarouter_sidecar_enabled),
            configured=settings.orcarouter_sidecar_api_key_encrypted is not None,
            status=status,
            message=message,
            base_url=settings.orcarouter_sidecar_base_url,
            model_count=len(models) if status == "healthy" else None,
            last_checked_at=checked_at,
            models=models,
        )


def _classify_static_status(settings) -> tuple[OrcaRouterSidecarStatus, str | None]:
    if not settings.orcarouter_sidecar_enabled:
        return "disabled", "OrcaRouter sidecar is disabled"
    if settings.orcarouter_sidecar_api_key_encrypted is None:
        return "missing_api_key", "OrcaRouter sidecar API key is not configured"
    return "healthy", None


def _classify_status(settings) -> tuple[OrcaRouterSidecarStatus, str | None]:
    static_status, static_message = _classify_static_status(settings)
    if static_status != "healthy":
        return static_status, static_message
    recorded_status = settings.orcarouter_sidecar_last_health_status
    if recorded_status in {"unreachable", "unauthorized", "healthy", "error"}:
        return recorded_status, None
    return "healthy", None


def _model_summaries(models) -> list[OrcaRouterSidecarModelSummary]:
    return [
        OrcaRouterSidecarModelSummary(id=model.id, created=model.created, owned_by=model.owned_by)
        for model in models
    ]


_REDACTION = "[redacted]"
# Token charset mirrors app/core/runtime_logging.py so the closing quote/brace of
# an echoed header survives while the credential does not.
_BEARER_TOKEN_RE = re.compile(r"(?i)(bearer[\s:=]+)[A-Za-z0-9._~+/=-]+")
# OrcaRouter keys carry an ``sk-orca-`` prefix and can be echoed bare, with no
# ``Bearer`` in front ("Invalid API key: sk-orca-...").
_ORCAROUTER_KEY_RE = re.compile(r"(?i)sk-orca-[A-Za-z0-9._~+/=-]+")


def _sanitize_message(message: str, *, api_key: str | None = None) -> str:
    """Strip the OrcaRouter credential out of an operator-visible health message.

    ``test_connection`` persists this string to
    ``orcarouter_sidecar_last_health_message`` and returns it on the dashboard
    status response, so an upstream that echoes the Authorization header must not
    be able to leak the key. The configured key is removed verbatim first - that
    is exact rather than pattern-guessed - and the ``Bearer``/``sk-orca-``
    patterns then cover keys that are no longer the configured one.
    """

    sanitized = message
    configured_key = (api_key or "").strip()
    if configured_key:
        sanitized = sanitized.replace(configured_key, _REDACTION)
    sanitized = _BEARER_TOKEN_RE.sub(rf"\g<1>{_REDACTION}", sanitized)
    return _ORCAROUTER_KEY_RE.sub(_REDACTION, sanitized)
