from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import NoReturn

from sqlalchemy.exc import IntegrityError

from app.core.audit.service import AuditService
from app.core.clients.claude_sidecar import ClaudeSidecarClient, ClaudeSidecarError, ClaudeSidecarUnavailableError
from app.core.exceptions import (
    DashboardAuthError,
    DashboardBadRequestError,
    DashboardConflictError,
    DashboardNotFoundError,
    DashboardServiceUnavailableError,
    DashboardUpstreamError,
)
from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping
from app.db.models import DashboardSettings
from app.modules.claude_sidecar.excluded_models import ExcludedModelsState
from app.modules.claude_sidecar.quota import (
    GrokCreditsQuota,
    SidecarAuthQuota,
    SidecarQuotaSnapshot,
    SidecarRateLimitHold,
    credential_provider,
    dashboard_status_for_auth,
    parse_auth_files,
    snapshot_from_json,
)
from app.modules.cliproxy_accounts.prefix_lock import PrefixWriteLockTimeout, cliproxy_prefix_write_lock
from app.modules.cliproxy_accounts.repository import CliproxyCredentialPrefixRepository
from app.modules.cliproxy_accounts.schemas import (
    CliproxyAccountsResponse,
    CliproxyAccountsStatus,
    CliproxyCredential,
    CliproxyCredentialFieldsResponse,
    CliproxyCredentialStatusResponse,
    CliproxyProviderCredentials,
    CliproxyQuotaWindow,
)
from app.modules.cliproxy_accounts.validation import (
    CredentialFieldChange,
    effective_prefixes,
    prefix_conflict_message,
    routing_prefix_owners,
)
from app.modules.proxy.claude_sidecar_dispatch import sidecar_config_from_settings
from app.modules.settings.repository import SettingsRepository

logger = logging.getLogger(__name__)


class CliproxyAccountsService:
    """List CLIProxyAPI credentials and edit their management fields.

    Writes go to CLIProxyAPI's auth-file field and status endpoints. Prefixes
    are also stored here, because the auth-file list does not return them.
    Nothing in this service dispatches a request or changes ``force-model-prefix``.
    """

    def __init__(
        self,
        settings_repository: SettingsRepository,
        prefixes: CliproxyCredentialPrefixRepository,
    ) -> None:
        self._settings_repository = settings_repository
        self._prefixes = prefixes

    async def list_credentials(self, *, provider: str | None = None) -> CliproxyAccountsResponse:
        settings = await self._settings_repository.get_or_create()
        guarded = _inventory_guard(settings)
        if guarded is not None:
            status, message = guarded
            return CliproxyAccountsResponse(status=status, message=message)

        client = ClaudeSidecarClient(sidecar_config_from_settings(settings))
        try:
            raw_files = await client.list_auth_files()
        except ClaudeSidecarUnavailableError as exc:
            return CliproxyAccountsResponse(status="unreachable", message=_sanitize_message(exc.message))
        except ClaudeSidecarError as exc:
            status: CliproxyAccountsStatus = "unauthorized" if exc.status_code in {401, 403} else "error"
            return CliproxyAccountsResponse(status=status, message=_sanitize_message(exc.message))

        accounts = await asyncio.to_thread(parse_auth_files, raw_files, provider=provider)
        quota = snapshot_from_json(settings.claude_sidecar_quota_state_json)
        holds = quota.rate_limit_holds if quota is not None else ()
        stored_prefixes = await self._stored_prefixes()
        raw_by_name = _raw_entries_by_name(raw_files)
        credentials = await asyncio.gather(
            *(
                _credential(
                    client,
                    account,
                    quota,
                    holds,
                    stored_prefixes.get(account.name),
                    raw_by_name.get(account.name),
                )
                for account in accounts
            )
        )
        grouped: dict[str, list[CliproxyCredential]] = defaultdict(list)
        for credential in credentials:
            grouped[credential.provider].append(credential)
        providers = [
            CliproxyProviderCredentials(provider=name, credentials=sorted(grouped[name], key=_credential_sort_key))
            for name in sorted(grouped)
        ]
        return CliproxyAccountsResponse(status="healthy", providers=providers)

    async def update_fields(self, name: str, change: CredentialFieldChange) -> CliproxyCredentialFieldsResponse:
        settings, account, raw, _accounts = await self._require_account(name)
        if change.update_excluded_models and not account.excluded_models_available:
            raise DashboardBadRequestError("Excluded models could not be read, so they cannot be replaced")
        if not change.update_prefix:
            await self._patch_fields(settings, name, change)
            _audit_fields(account, change)
            return _fields_response(account, raw, change, await self._stored_prefixes())
        try:
            async with cliproxy_prefix_write_lock(self._prefixes.session):
                return await self._update_prefix_fields(name, change)
        except PrefixWriteLockTimeout as exc:
            raise DashboardConflictError("Another credential prefix update is in progress") from exc

    async def _update_prefix_fields(self, name: str, change: CredentialFieldChange) -> CliproxyCredentialFieldsResponse:
        """Patch one prefix while this worker holds the cross-process write lock.

        The lock is already held. Re-read the registry inside it so an older
        request cannot commit after a newer upstream PATCH, then put the
        previous prefix back upstream if the registry commit fails.
        """

        settings, account, raw, accounts = await self._require_account(name)
        stored = await self._stored_prefixes()
        if change.prefix:
            message = prefix_conflict_message(
                change.prefix,
                credential_name=name,
                effective=effective_prefixes(accounts, stored),
                routing_owners=routing_prefix_owners(settings),
            )
            if message is not None:
                raise DashboardConflictError(message)
        previous = stored.get(account.name) or account.prefix or ""
        # Build the client before the registry flush. A failed flush expires
        # ``settings``, and reading it again raises PendingRollbackError
        # before the previous prefix can be put back upstream.
        client = ClaudeSidecarClient(sidecar_config_from_settings(settings))
        await _send_auth_file_fields(client, name, _field_payload(change))
        try:
            await self._store_prefix(account, change.prefix)
        except IntegrityError as exc:
            await self._compensate_failed_prefix_store(client, name, previous)
            raise DashboardConflictError(f"Prefix {change.prefix} is already assigned to another credential") from exc
        except Exception:
            await self._compensate_failed_prefix_store(client, name, previous)
            raise
        _audit_fields(account, change)
        return _fields_response(account, raw, change, await self._stored_prefixes())

    async def set_credential_disabled(self, name: str, *, disabled: bool) -> CliproxyCredentialStatusResponse:
        """Enable or disable one credential.

        The panel route confirms with the operator before calling this. A
        later delete flow can call it after its own confirmation, then delete.
        """

        settings, account, _raw, _accounts = await self._require_account(name)
        client = ClaudeSidecarClient(sidecar_config_from_settings(settings))
        try:
            await client.patch_auth_file_status(name, disabled=disabled, auth_index=account.auth_index)
        except ClaudeSidecarUnavailableError as exc:
            raise DashboardServiceUnavailableError(_sanitize_message(exc.message)) from exc
        except ClaudeSidecarError as exc:
            _raise_management_error(exc)
        AuditService.log_async(
            "cliproxy_credential_status_updated",
            details={
                "credential_name": account.name,
                "provider": account.provider or "unknown",
                "disabled": disabled,
            },
        )
        return CliproxyCredentialStatusResponse(name=account.name, disabled=disabled)

    async def _require_account(
        self, name: str
    ) -> tuple[DashboardSettings, SidecarAuthQuota, Mapping[str, JsonValue] | None, list[SidecarAuthQuota]]:
        settings = await self._settings_repository.get_or_create()
        guarded = _inventory_guard(settings)
        if guarded is not None:
            _status, message = guarded
            raise DashboardBadRequestError(message)
        client = ClaudeSidecarClient(sidecar_config_from_settings(settings))
        try:
            raw_files = await client.list_auth_files()
        except ClaudeSidecarUnavailableError as exc:
            raise DashboardServiceUnavailableError(_sanitize_message(exc.message)) from exc
        except ClaudeSidecarError as exc:
            _raise_management_error(exc)
        accounts = await asyncio.to_thread(parse_auth_files, raw_files, provider=None)
        account = next((item for item in accounts if item.name == name), None)
        if account is None:
            raise DashboardNotFoundError("CLIProxyAPI credential was not found")
        return settings, account, _raw_entries_by_name(raw_files).get(name), accounts

    async def _stored_prefixes(self) -> dict[str, str]:
        rows = await self._prefixes.list_all()
        return {row.credential_name: row.prefix for row in rows}

    async def _patch_fields(self, settings: DashboardSettings, name: str, change: CredentialFieldChange) -> None:
        client = ClaudeSidecarClient(sidecar_config_from_settings(settings))
        await _send_auth_file_fields(client, name, _field_payload(change))

    async def _restore_prefix(self, client: ClaudeSidecarClient, name: str, previous: str) -> None:
        try:
            await client.patch_auth_file_fields(name, {"prefix": previous})
        except (ClaudeSidecarError, ClaudeSidecarUnavailableError):
            logger.warning("CLIProxyAPI prefix restore failed after the registry commit failed", exc_info=True)

    async def _compensate_failed_prefix_store(self, client: ClaudeSidecarClient, name: str, previous: str) -> None:
        try:
            await self._restore_prefix(client, name, previous)
        finally:
            await self._prefixes.session.rollback()

    async def _store_prefix(self, account: SidecarAuthQuota, prefix: str | None) -> None:
        if prefix:
            await self._prefixes.upsert(
                credential_name=account.name,
                auth_index=account.auth_index,
                prefix=prefix,
            )
        else:
            await self._prefixes.delete(account.name)
        await self._prefixes.session.flush()
        await self._prefixes.session.commit()


async def _send_auth_file_fields(client: ClaudeSidecarClient, name: str, fields: Mapping[str, JsonValue]) -> None:
    try:
        await client.patch_auth_file_fields(name, fields)
    except ClaudeSidecarUnavailableError as exc:
        raise DashboardServiceUnavailableError(_sanitize_message(exc.message)) from exc
    except ClaudeSidecarError as exc:
        _raise_management_error(exc)


def _inventory_guard(settings: DashboardSettings) -> tuple[CliproxyAccountsStatus, str] | None:
    base_url = (settings.claude_sidecar_base_url or "").strip()
    if not base_url:
        return "not_configured", "CLIProxyAPI base URL is not configured"
    if not settings.claude_sidecar_management_key_encrypted:
        return "not_configured", "CLIProxyAPI management key is not configured"
    return None


async def _credential(
    client: ClaudeSidecarClient,
    account: SidecarAuthQuota,
    stored: SidecarQuotaSnapshot | None,
    holds: tuple[SidecarRateLimitHold, ...],
    stored_prefix: str | None,
    raw: Mapping[str, JsonValue] | None,
) -> CliproxyCredential:
    models, models_error = await _models_for(client, account.name)
    provider = (account.provider or "unknown").strip().lower() or "unknown"
    credits = _stored_grok_credits(stored, account)
    windows = [
        CliproxyQuotaWindow(
            id=window.id,
            label=window.label,
            kind=window.kind,
            percent_remaining=window.percent_remaining,
            resets_at=window.resets_at,
        )
        for window in (credits.windows if credits is not None else ())
    ]
    rollup = credits.token_rollup if credits is not None else None
    excluded_state: ExcludedModelsState = "available" if account.excluded_models_available else "unreadable"
    return CliproxyCredential(
        name=account.name,
        auth_index=account.auth_index,
        email=account.email,
        provider=provider,
        health=_credential_health(account, holds),
        disabled=account.disabled,
        unavailable=account.unavailable,
        quota_exceeded=account.quota_exceeded,
        prefix=stored_prefix if stored_prefix else account.prefix,
        weight=_json_int(raw.get("weight")) if raw is not None else None,
        priority=_json_int(raw.get("priority")) if raw is not None else None,
        excluded_models=list(account.excluded_models),
        excluded_models_state=excluded_state,
        models=models,
        models_error=models_error,
        quota_windows=windows,
        prepaid_credits=credits.prepaid_credits if credits is not None else None,
        usage_tokens=rollup.total_tokens if rollup is not None else None,
        usage_requests=rollup.request_count if rollup is not None else None,
    )


async def _models_for(client: ClaudeSidecarClient, name: str) -> tuple[list[str], str | None]:
    if not name:
        return [], "Credential has no name"
    try:
        return await client.list_auth_file_models(name), None
    except ClaudeSidecarUnavailableError as exc:
        return [], _sanitize_message(exc.message)
    except ClaudeSidecarError as exc:
        return [], _sanitize_message(exc.message)


def _stored_grok_credits(
    stored: SidecarQuotaSnapshot | None,
    account: SidecarAuthQuota,
) -> GrokCreditsQuota | None:
    if stored is None:
        return None
    provider = credential_provider(account.provider)
    named: GrokCreditsQuota | None = None
    for row in stored.accounts:
        if credential_provider(row.provider) != provider or row.grok_credits is None:
            continue
        if account.auth_index and row.auth_index == account.auth_index:
            return row.grok_credits
        if named is None and account.name and row.name == account.name:
            named = row.grok_credits
    return named


def _credential_health(account: SidecarAuthQuota, holds: tuple[SidecarRateLimitHold, ...] = ()) -> str:
    mapped = dashboard_status_for_auth(account, holds)
    if credential_provider(account.provider) != "claude" and mapped == "rate_limited":
        return "rate_limited"
    if account.disabled:
        return "paused"
    if mapped == "reauth_required":
        return "reauth_required"
    if account.quota_exceeded:
        return "quota_exceeded"
    if account.unavailable:
        return "unavailable"
    if mapped:
        return mapped
    return "active"


def _credential_sort_key(credential: CliproxyCredential) -> tuple[str, str]:
    return ((credential.email or credential.name).casefold(), credential.name.casefold())


def _raw_entries_by_name(
    raw_files: Sequence[Mapping[str, JsonValue]],
) -> dict[str, Mapping[str, JsonValue]]:
    indexed: dict[str, Mapping[str, JsonValue]] = {}
    for entry in raw_files:
        if not is_json_mapping(entry):
            continue
        name = _entry_name(entry)
        if name and name not in indexed:
            indexed[name] = entry
    return indexed


def _entry_name(entry: Mapping[str, JsonValue]) -> str:
    for key in ("name", "id", "label"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _json_int(value: JsonValue | None) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _field_payload(change: CredentialFieldChange) -> dict[str, JsonValue]:
    payload: dict[str, JsonValue] = {}
    if change.update_prefix:
        payload["prefix"] = change.prefix or ""
    if change.update_weight:
        payload["weight"] = change.weight
    if change.update_priority:
        payload["priority"] = change.priority
    if change.update_excluded_models:
        payload["excluded_models"] = list(change.excluded_models or ())
    return payload


def _fields_response(
    account: SidecarAuthQuota,
    raw: Mapping[str, JsonValue] | None,
    change: CredentialFieldChange,
    stored: Mapping[str, str],
) -> CliproxyCredentialFieldsResponse:
    if change.update_prefix:
        prefix = change.prefix
    elif account.name in stored:
        prefix = stored[account.name]
    else:
        prefix = account.prefix
    excluded_state: ExcludedModelsState = "available" if account.excluded_models_available else "unreadable"
    excluded = list(change.excluded_models or ()) if change.update_excluded_models else list(account.excluded_models)
    return CliproxyCredentialFieldsResponse(
        name=account.name,
        prefix=prefix,
        weight=change.weight if change.update_weight else _json_int(None if raw is None else raw.get("weight")),
        priority=change.priority if change.update_priority else _json_int(None if raw is None else raw.get("priority")),
        excluded_models=excluded,
        excluded_models_state=excluded_state,
        disabled=account.disabled,
    )


def _audit_fields(account: SidecarAuthQuota, change: CredentialFieldChange) -> None:
    details: dict[str, str | int | bool | None | list[str]] = {
        "credential_name": account.name,
        "provider": account.provider or "unknown",
        "changed_fields": list(change.changed_fields),
    }
    if change.update_prefix:
        details["prefix"] = change.prefix
    if change.update_weight:
        details["weight"] = change.weight
    if change.update_priority:
        details["priority"] = change.priority
    if change.update_excluded_models:
        details["excluded_models"] = list(change.excluded_models or ())
    AuditService.log_async("cliproxy_credential_fields_updated", details=details)


def _raise_management_error(exc: ClaudeSidecarError) -> NoReturn:
    if exc.status_code == 404:
        raise DashboardNotFoundError("CLIProxyAPI credential was not found") from exc
    if exc.status_code == 409:
        raise DashboardConflictError(_sanitize_message(exc.message)) from exc
    if exc.status_code in {401, 403}:
        raise DashboardAuthError("CLIProxyAPI management key was rejected") from exc
    raise DashboardUpstreamError(_sanitize_message(exc.message)) from exc


def _sanitize_message(message: str) -> str:
    return message.replace("Bearer ", "Bearer [redacted]")
