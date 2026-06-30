from __future__ import annotations

from datetime import datetime, timezone

from app.core.clients.claude_sidecar import ClaudeSidecarClient, ClaudeSidecarError, ClaudeSidecarUnavailableError
from app.core.config.settings_cache import get_settings_cache
from app.modules.accounts.schemas import SidecarAuthAccount
from app.modules.claude_sidecar.quota import SidecarAuthQuota, snapshot_from_json
from app.modules.claude_sidecar.schemas import (
    ClaudeSidecarModelsResponse,
    ClaudeSidecarModelSummary,
    ClaudeSidecarQuotaResponse,
    ClaudeSidecarRoutingAccount,
    ClaudeSidecarRoutingResponse,
    ClaudeSidecarRoutingStatus,
    ClaudeSidecarRoutingStrategy,
    ClaudeSidecarStatus,
    ClaudeSidecarStatusResponse,
    ClaudeSidecarTestResponse,
)
from app.modules.claude_sidecar.usage_estimates import (
    SECONDARY_WINDOW,
    ClaudeAuthUsageEstimate,
    build_claude_usage_estimates,
)
from app.modules.claude_sidecar.usage_repository import ClaudeSidecarUsageRepository
from app.modules.proxy.claude_sidecar_dispatch import sidecar_config_from_settings
from app.modules.settings.repository import SettingsRepository
from app.modules.settings.service import parse_claude_sidecar_auth_plans


_STRATEGY_TO_WIRE: dict[ClaudeSidecarRoutingStrategy, str] = {
    "round_robin": "round-robin",
    "fill_first": "fill-first",
}
_WIRE_TO_STRATEGY: dict[str, ClaudeSidecarRoutingStrategy] = {
    value: key for key, value in _STRATEGY_TO_WIRE.items()
}


class ClaudeSidecarService:
    def __init__(
        self,
        settings_repository: SettingsRepository,
        usage_repository: ClaudeSidecarUsageRepository | None = None,
    ) -> None:
        self._settings_repository = settings_repository
        self._usage_repository = usage_repository

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

    async def get_quota(self) -> ClaudeSidecarQuotaResponse:
        settings = await self._settings_repository.get_or_create()
        if not settings.claude_sidecar_enabled:
            return ClaudeSidecarQuotaResponse(status="disabled", message="Claude sidecar is disabled")
        if not settings.claude_sidecar_management_key_encrypted:
            return ClaudeSidecarQuotaResponse(
                status="not_configured",
                message="Claude sidecar management key is not configured",
            )
        snapshot = snapshot_from_json(settings.claude_sidecar_quota_state_json)
        if snapshot is None:
            return ClaudeSidecarQuotaResponse(
                status="unknown",
                message="Claude sidecar quota has not been polled yet",
                checked_at=settings.claude_sidecar_quota_checked_at,
            )
        estimates_by_key: dict[str, ClaudeAuthUsageEstimate] = {}
        if self._usage_repository is not None:
            now = datetime.now(timezone.utc)
            events = await self._usage_repository.list_events_since(now - SECONDARY_WINDOW)
            estimates = build_claude_usage_estimates(
                events=events,
                plans=parse_claude_sidecar_auth_plans(settings.claude_sidecar_auth_plans_json),
                snapshot=snapshot,
                now=now,
            )
            estimates_by_key = {
                key: estimate
                for estimate in estimates.accounts
                if (key := _estimate_key(estimate)) is not None
            }
        return ClaudeSidecarQuotaResponse(
            status=snapshot.status,
            message=snapshot.message,
            checked_at=snapshot.checked_at,
            accounts=[
                _to_auth_account(auth, estimates_by_key.get(_auth_key(auth) or ""))
                for auth in snapshot.accounts
            ],
        )

    async def get_routing(self) -> ClaudeSidecarRoutingResponse:
        settings = await self._settings_repository.get_or_create()
        guarded = _routing_guard(settings)
        if guarded is not None:
            status, message = guarded
            return ClaudeSidecarRoutingResponse(status=status, message=message)

        client = ClaudeSidecarClient(sidecar_config_from_settings(settings))
        try:
            wire_strategy = await client.get_routing_strategy()
            auth_files = await client.list_auth_files()
        except ClaudeSidecarUnavailableError as exc:
            return ClaudeSidecarRoutingResponse(status="unreachable", message=_sanitize_message(exc.message))
        except ClaudeSidecarError as exc:
            status: ClaudeSidecarRoutingStatus = "unauthorized" if exc.status_code in {401, 403} else "error"
            return ClaudeSidecarRoutingResponse(status=status, message=_sanitize_message(exc.message))

        return ClaudeSidecarRoutingResponse(
            status="healthy",
            strategy=_WIRE_TO_STRATEGY.get(wire_strategy),
            accounts=_routing_accounts(auth_files),
        )

    async def set_routing_strategy(
        self,
        strategy: ClaudeSidecarRoutingStrategy,
    ) -> ClaudeSidecarRoutingResponse:
        settings = await self._settings_repository.get_or_create()
        guarded = _routing_guard(settings)
        if guarded is not None:
            status, message = guarded
            return ClaudeSidecarRoutingResponse(status=status, message=message)

        client = ClaudeSidecarClient(sidecar_config_from_settings(settings))
        try:
            await client.set_routing_strategy(_STRATEGY_TO_WIRE[strategy])
        except ClaudeSidecarUnavailableError as exc:
            return ClaudeSidecarRoutingResponse(status="unreachable", message=_sanitize_message(exc.message))
        except ClaudeSidecarError as exc:
            status: ClaudeSidecarRoutingStatus = "unauthorized" if exc.status_code in {401, 403} else "error"
            return ClaudeSidecarRoutingResponse(status=status, message=_sanitize_message(exc.message))
        return await self.get_routing()

    async def set_account_priority(self, name: str, priority: int) -> ClaudeSidecarRoutingResponse:
        settings = await self._settings_repository.get_or_create()
        guarded = _routing_guard(settings)
        if guarded is not None:
            status, message = guarded
            return ClaudeSidecarRoutingResponse(status=status, message=message)

        client = ClaudeSidecarClient(sidecar_config_from_settings(settings))
        try:
            await client.patch_auth_file_priority(name, priority)
        except ClaudeSidecarUnavailableError as exc:
            return ClaudeSidecarRoutingResponse(status="unreachable", message=_sanitize_message(exc.message))
        except ClaudeSidecarError as exc:
            status: ClaudeSidecarRoutingStatus = "unauthorized" if exc.status_code in {401, 403} else "error"
            message = "Claude sidecar account not found" if exc.status_code == 404 else _sanitize_message(exc.message)
            return ClaudeSidecarRoutingResponse(status=status, message=message)
        return await self.get_routing()

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


def _routing_guard(settings) -> tuple[ClaudeSidecarRoutingStatus, str] | None:
    if not settings.claude_sidecar_enabled:
        return "disabled", "Claude sidecar is disabled"
    if not settings.claude_sidecar_management_key_encrypted:
        return "not_configured", "Claude sidecar management key is not configured"
    return None


def _routing_accounts(auth_files) -> list[ClaudeSidecarRoutingAccount]:
    accounts: list[ClaudeSidecarRoutingAccount] = []
    for entry in auth_files:
        provider = entry.get("provider")
        auth_type = entry.get("type")
        if provider != "claude" and auth_type != "claude":
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        auth_index = entry.get("auth_index")
        email = entry.get("email")
        accounts.append(
            ClaudeSidecarRoutingAccount(
                name=name,
                auth_index=auth_index if isinstance(auth_index, str) else None,
                email=email if isinstance(email, str) else None,
                priority=_priority_value(entry.get("priority")),
            )
        )
    return accounts


def _priority_value(value) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


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


def _to_auth_account(
    auth: SidecarAuthQuota,
    estimate: ClaudeAuthUsageEstimate | None = None,
) -> SidecarAuthAccount:
    return SidecarAuthAccount(
        name=auth.name,
        auth_index=auth.auth_index,
        email=auth.email,
        status=auth.status,
        quota_exceeded=auth.quota_exceeded,
        next_recover_at=auth.next_recover_at,
        models_exceeded=[entry.model for entry in auth.model_states if entry.quota_exceeded],
        success=auth.success,
        failed=auth.failed,
        plan_type=estimate.plan_type if estimate else None,
        usage_source=estimate.usage_source if estimate else None,
        primary_remaining_percent=estimate.primary_remaining_percent if estimate else None,
        secondary_remaining_percent=estimate.secondary_remaining_percent if estimate else None,
        primary_used_tokens=estimate.primary_used_tokens if estimate else None,
        secondary_used_tokens=estimate.secondary_used_tokens if estimate else None,
        primary_token_budget=estimate.primary_token_budget if estimate else None,
        secondary_token_budget=estimate.secondary_token_budget if estimate else None,
        reset_at_primary=estimate.reset_at_primary if estimate else None,
        reset_at_secondary=estimate.reset_at_secondary if estimate else None,
        confidence=estimate.confidence if estimate else None,
    )


def _auth_key(auth: SidecarAuthQuota) -> str | None:
    if auth.auth_index:
        return f"auth:{auth.auth_index}"
    if auth.email:
        return f"source:{auth.email.lower()}"
    return None


def _estimate_key(estimate: ClaudeAuthUsageEstimate) -> str | None:
    if estimate.auth_index:
        return f"auth:{estimate.auth_index}"
    if estimate.email:
        return f"source:{estimate.email.lower()}"
    if estimate.source:
        return f"source:{estimate.source.lower()}"
    return None
