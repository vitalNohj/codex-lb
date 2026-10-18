from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import NoReturn

from sqlalchemy.ext.asyncio import AsyncSession

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
from app.modules.cliproxy_accounts.api_keys import (
    ApiKeyWrite,
    api_key_kind,
    create_api_key_account,
    delete_api_key_account,
    list_api_key_accounts,
    shared_model_ids,
    stored_api_key_prefixes,
    update_api_key_account,
)
from app.modules.cliproxy_accounts.management import CliproxyManagement, build_management
from app.modules.cliproxy_accounts.oauth_flow import (
    callback_body,
    claim_oauth_completion,
    project_callback,
    project_cancel,
    project_start,
    project_status,
    remember_oauth_provider,
    remembered_oauth_provider,
    validate_oauth_state,
)
from app.modules.cliproxy_accounts.providers import OauthProvider, oauth_provider
from app.modules.cliproxy_accounts.redaction import public_message
from app.modules.cliproxy_accounts.refresh_jobs import (
    RefreshObservation,
    RefreshStatus,
    begin_refresh,
    current_refresh,
)
from app.modules.cliproxy_accounts.schemas import (
    CliproxyAccountsResponse,
    CliproxyAccountsStatus,
    CliproxyApiKeyAccount,
    CliproxyCatalogModelResponse,
    CliproxyCredential,
    CliproxyCredentialDeleteResponse,
    CliproxyCredentialFieldsResponse,
    CliproxyCredentialRefreshResponse,
    CliproxyCredentialStatusResponse,
    CliproxyCredentialUploadResponse,
    CliproxyOauthCallbackResponse,
    CliproxyOauthCancelResponse,
    CliproxyOauthStartResponse,
    CliproxyOauthStatusResponse,
    CliproxyProviderCredentials,
    CliproxyQuotaWindow,
)
from app.modules.cliproxy_accounts.status_lock import (
    ApiKeyWriteLockTimeout,
    PrefixWriteLockTimeout,
    StatusWriteLockTimeout,
    cliproxy_api_key_list_lock,
    cliproxy_prefix_write_lock,
    cliproxy_status_write_lock,
)
from app.modules.cliproxy_accounts.upload import normalize_credential_name, prepare_upload_document
from app.modules.cliproxy_accounts.validation import (
    CredentialFieldChange,
    disabling_last_enabled_account,
    reject_duplicate_prefix,
)
from app.modules.proxy.claude_sidecar_dispatch import sidecar_config_from_settings
from app.modules.proxy.cliproxy_account_routing import forget_remembered_prefixes
from app.modules.proxy.sidecar_routing import parse_sidecar_full_models
from app.modules.settings.repository import SettingsRepository


class CliproxyAccountsService:
    """List CLIProxyAPI credentials and edit their management fields.

    Writes go to CLIProxyAPI's auth-file field and status endpoints, and to
    the API-key config lists. A stored prefix changes only when the operator
    sends a new one. Nothing here rewrites the model on a request.
    """

    def __init__(self, settings_repository: SettingsRepository, session: AsyncSession) -> None:
        self._settings_repository = settings_repository
        self._session = session

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

        oauth_files = _oauth_files(raw_files)
        accounts = await asyncio.to_thread(parse_auth_files, oauth_files, provider=provider)
        quota = snapshot_from_json(settings.claude_sidecar_quota_state_json)
        holds = quota.rate_limit_holds if quota is not None else ()
        raw_by_name = _raw_entries_by_name(oauth_files)
        credentials = list(
            await asyncio.gather(
                *(_credential(client, account, quota, holds, raw_by_name.get(account.name)) for account in accounts)
            )
        )
        api_keys, api_keys_message = await self._api_keys(client, raw_files)
        grouped: dict[str, list[CliproxyCredential]] = defaultdict(list)
        for credential in credentials:
            grouped[credential.provider].append(credential)
        providers = [
            CliproxyProviderCredentials(provider=name, credentials=sorted(grouped[name], key=_credential_sort_key))
            for name in sorted(grouped)
        ]
        return CliproxyAccountsResponse(
            status="healthy",
            providers=providers,
            api_keys=api_keys,
            api_keys_message=api_keys_message,
            shared_model_ids=shared_model_ids(credentials, api_keys),
        )

    async def update_fields(self, name: str, change: CredentialFieldChange) -> CliproxyCredentialFieldsResponse:
        settings, account, raw, _accounts = await self._require_account(name)
        if change.update_excluded_models and not account.excluded_models_available:
            raise DashboardBadRequestError("Excluded models could not be read, so they cannot be replaced")
        await self._patch_fields(settings, name, change)
        _audit_fields(account, change)
        return _fields_response(account, raw, change)

    async def set_credential_disabled(
        self,
        name: str,
        *,
        disabled: bool,
        confirm: bool,
    ) -> CliproxyCredentialStatusResponse:
        """Enable or disable one credential.

        Only turning off the last enabled account asks for confirmation. The
        inventory is loaded again inside the status write lock, so two overlapping
        disables cannot both observe the other account as still enabled. Delete
        uses ``_patch_disabled`` directly so the captain's one delete action
        does not also write the status audit entry.
        """

        try:
            async with cliproxy_status_write_lock(self._session):
                settings, account, _raw, accounts = await self._require_account(name)
                if disabling_last_enabled_account(accounts, name=account.name, disabled=disabled) and not confirm:
                    raise DashboardBadRequestError("Confirm before disabling the last enabled CLIProxyAPI account")
                client = ClaudeSidecarClient(sidecar_config_from_settings(settings))
                await _patch_disabled(client, account, disabled=disabled)
        except StatusWriteLockTimeout as exc:
            raise DashboardConflictError("Another credential status update is in progress") from exc
        AuditService.log_async(
            "cliproxy_credential_status_updated",
            details={
                "credential_name": account.name,
                "provider": account.provider or "unknown",
                "disabled": disabled,
            },
        )
        return CliproxyCredentialStatusResponse(name=account.name, disabled=disabled)

    async def start_oauth(self, provider_slug: str) -> CliproxyOauthStartResponse:
        provider = _require_oauth_provider(provider_slug)
        settings = await self._ready_settings()
        client = ClaudeSidecarClient(sidecar_config_from_settings(settings))
        payload = await _management_call(client, lambda management: management.start_oauth(provider.management_path))
        started = project_start(provider, payload)
        remember_oauth_provider(started.state, provider.panel)
        return started

    async def oauth_status(self, state: str) -> CliproxyOauthStatusResponse:
        safe_state = validate_oauth_state(state)
        settings = await self._ready_settings()
        client = ClaudeSidecarClient(sidecar_config_from_settings(settings))
        payload = await _management_call(client, lambda management: management.auth_status(safe_state))
        status = project_status(payload)
        if status.status == "success" and claim_oauth_completion(safe_state):
            details: dict[str, str] = {"state": safe_state}
            provider = remembered_oauth_provider(safe_state)
            if provider is not None:
                details["provider"] = provider
            AuditService.log_async("cliproxy_oauth_completed", details=details)
        return status

    async def cancel_oauth(self, state: str) -> CliproxyOauthCancelResponse:
        safe_state = validate_oauth_state(state)
        settings = await self._ready_settings()
        client = ClaudeSidecarClient(sidecar_config_from_settings(settings))
        payload = await _management_call(client, lambda management: management.cancel_oauth(safe_state))
        return project_cancel(payload)

    async def submit_oauth_callback(
        self,
        *,
        provider_slug: str,
        state: str,
        callback_url: str,
    ) -> CliproxyOauthCallbackResponse:
        provider = _require_oauth_provider(provider_slug)
        safe_state = validate_oauth_state(state)
        remembered = remembered_oauth_provider(safe_state)
        if remembered is not None:
            started = oauth_provider(remembered)
            if started is None or started.management_path != provider.management_path:
                raise DashboardBadRequestError("Sign-in provider does not match this session")
        body = callback_body(provider, safe_state, callback_url)
        settings = await self._ready_settings()
        client = ClaudeSidecarClient(sidecar_config_from_settings(settings))
        payload = await _management_call(client, lambda management: management.submit_callback(body))
        return project_callback(payload)

    async def start_refresh(self, name: str) -> CliproxyCredentialRefreshResponse:
        settings, account, _raw, _accounts = await self._require_account(name)
        client = ClaudeSidecarClient(sidecar_config_from_settings(settings))
        management = build_management(client)
        credential_name = account.name
        provider = account.provider or "unknown"
        auth_index = account.auth_index

        async def runner() -> None:
            await management.refresh_auth_file(credential_name, auth_index)

        def on_done(status: RefreshStatus, message: str | None) -> None:
            if status == "pending":
                return
            details: dict[str, str] = {
                "credential_name": credential_name,
                "provider": provider,
                "status": status,
            }
            if message:
                details["message"] = message
            AuditService.log_async("cliproxy_credential_refreshed", details=details)

        observation = await begin_refresh(credential_name, runner, on_done)
        return _refresh_response(observation)

    async def refresh_status(self, name: str) -> CliproxyCredentialRefreshResponse:
        safe_name = name.strip()
        observation = current_refresh(safe_name)
        if observation is None:
            raise DashboardNotFoundError("CLIProxyAPI credential refresh was not found")
        return _refresh_response(observation)

    async def delete_credential(self, name: str) -> CliproxyCredentialDeleteResponse:
        """Turn the credential off, then delete it.

        Disable and delete are one captain action. A failed disable does not
        delete. A failed delete leaves the credential disabled and says so.
        """

        settings, account, _raw, _accounts = await self._require_account(name)
        client = ClaudeSidecarClient(sidecar_config_from_settings(settings))
        await _patch_disabled(client, account, disabled=True)
        try:
            await build_management(client).delete_auth_file(account.name)
        except ClaudeSidecarUnavailableError as exc:
            _audit_delete(account, deleted=False, message=public_message(exc.message))
            raise DashboardUpstreamError(_delete_failed_message(exc.message)) from exc
        except ClaudeSidecarError as exc:
            _audit_delete(account, deleted=False, message=public_message(exc.message))
            raise DashboardUpstreamError(_delete_failed_message(exc.message)) from exc
        _audit_delete(account, deleted=True, message=None)
        return CliproxyCredentialDeleteResponse(name=account.name, disabled=True, deleted=True)

    async def upload_credential(self, name: str, document: str) -> CliproxyCredentialUploadResponse:
        safe_name = normalize_credential_name(name)
        prepared = prepare_upload_document(document)
        await self._upload_file(safe_name, prepared.provider, prepared.body, prefix=prepared.prefix)
        return CliproxyCredentialUploadResponse(
            name=safe_name,
            provider=prepared.provider,
            prefix=prepared.prefix,
        )

    async def create_api_key(self, write: ApiKeyWrite) -> CliproxyApiKeyAccount:
        try:
            async with cliproxy_api_key_list_lock(self._session, write.kind):
                client, raw_files = await self._management_client()
                account = await create_api_key_account(client, raw_files, write)
        except ApiKeyWriteLockTimeout as exc:
            raise DashboardConflictError("Another API-key account update is in progress") from exc
        except ClaudeSidecarUnavailableError as exc:
            raise DashboardServiceUnavailableError(public_message(exc.message)) from exc
        except ClaudeSidecarError as exc:
            _raise_management_error(exc)
        _audit_api_key("cliproxy_api_key_created", account)
        return account

    async def update_api_key(self, index: int, write: ApiKeyWrite, account_id: str) -> CliproxyApiKeyAccount:
        try:
            if write.update_prefix and write.prefix:
                async with cliproxy_prefix_write_lock(self._session):
                    client, raw_files = await self._management_client()
                    await _reject_prefix_collision(
                        client,
                        write.prefix,
                        skip_api_key=(write.kind, index),
                    )
                    async with cliproxy_api_key_list_lock(self._session, write.kind):
                        account = await update_api_key_account(client, raw_files, index, write, account_id)
            else:
                async with cliproxy_api_key_list_lock(self._session, write.kind):
                    client, raw_files = await self._management_client()
                    account = await update_api_key_account(client, raw_files, index, write, account_id)
        except PrefixWriteLockTimeout as exc:
            raise DashboardConflictError("Another CLIProxyAPI prefix update is in progress") from exc
        except ApiKeyWriteLockTimeout as exc:
            raise DashboardConflictError("Another API-key account update is in progress") from exc
        except ClaudeSidecarUnavailableError as exc:
            raise DashboardServiceUnavailableError(public_message(exc.message)) from exc
        except ClaudeSidecarError as exc:
            _raise_management_error(exc)
        if write.update_prefix and write.prefix:
            forget_remembered_prefixes()
        _audit_api_key("cliproxy_api_key_updated", account)
        return account

    async def delete_api_key(self, kind: str, index: int, account_id: str) -> None:
        resolved = api_key_kind(kind)
        try:
            async with cliproxy_api_key_list_lock(self._session, resolved.slug):
                client, _raw_files = await self._management_client()
                await delete_api_key_account(client, resolved.slug, index, account_id)
        except ApiKeyWriteLockTimeout as exc:
            raise DashboardConflictError("Another API-key account update is in progress") from exc
        except ClaudeSidecarUnavailableError as exc:
            raise DashboardServiceUnavailableError(public_message(exc.message)) from exc
        except ClaudeSidecarError as exc:
            _raise_management_error(exc)
        AuditService.log_async(
            "cliproxy_api_key_deleted",
            details={"kind": resolved.slug, "index": index},
        )

    async def add_catalog_model(self, model: str) -> CliproxyCatalogModelResponse:
        """Pin one discovered model id on the CLIProxyAPI full-model list."""

        text = model.strip()
        if not text or len(text) > 200 or any(char.isspace() for char in text):
            raise DashboardBadRequestError("Model id must be a single token")
        settings = await self._ready_settings()
        current = list(parse_sidecar_full_models(settings.claude_sidecar_full_models_json))
        if text.casefold() not in {item.casefold() for item in current}:
            current.append(text)
            await self._settings_repository.update(claude_sidecar_full_models_json=json.dumps(current))
        return CliproxyCatalogModelResponse(model=text, full_models=current)

    async def _management_client(self) -> tuple[ClaudeSidecarClient, list[Mapping[str, JsonValue]]]:
        settings = await self._ready_settings()
        client = ClaudeSidecarClient(sidecar_config_from_settings(settings))
        try:
            raw_files = await client.list_auth_files()
        except ClaudeSidecarUnavailableError as exc:
            raise DashboardServiceUnavailableError(public_message(exc.message)) from exc
        except ClaudeSidecarError as exc:
            _raise_management_error(exc)
        return client, raw_files

    async def _api_keys(
        self,
        client: ClaudeSidecarClient,
        raw_files: Sequence[Mapping[str, JsonValue]],
    ) -> tuple[list[CliproxyApiKeyAccount], str | None]:
        try:
            return await list_api_key_accounts(client, raw_files)
        except ClaudeSidecarUnavailableError as exc:
            return [], _sanitize_message(exc.message)

    async def _upload_file(self, name: str, provider: str, body: bytes, *, prefix: str | None) -> None:
        settings = await self._ready_settings()
        client = ClaudeSidecarClient(sidecar_config_from_settings(settings))
        await _upload_auth_file(client, name, body)
        _audit_upload(name, provider, prefix)

    async def _ready_settings(self) -> DashboardSettings:
        settings = await self._settings_repository.get_or_create()
        guarded = _inventory_guard(settings)
        if guarded is not None:
            _status, message = guarded
            raise DashboardBadRequestError(message)
        return settings

    async def _load_accounts(self) -> tuple[DashboardSettings, list[SidecarAuthQuota]]:
        settings = await self._ready_settings()
        client = ClaudeSidecarClient(sidecar_config_from_settings(settings))
        try:
            raw_files = await client.list_auth_files()
        except ClaudeSidecarUnavailableError as exc:
            raise DashboardServiceUnavailableError(public_message(exc.message)) from exc
        except ClaudeSidecarError as exc:
            _raise_management_error(exc)
        accounts = await asyncio.to_thread(parse_auth_files, _oauth_files(raw_files), provider=None)
        return settings, accounts

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
        oauth_files = _oauth_files(raw_files)
        accounts = await asyncio.to_thread(parse_auth_files, oauth_files, provider=None)
        account = next((item for item in accounts if item.name == name), None)
        if account is None:
            raise DashboardNotFoundError("CLIProxyAPI credential was not found")
        return settings, account, _raw_entries_by_name(oauth_files).get(name), accounts

    async def _patch_fields(self, settings: DashboardSettings, name: str, change: CredentialFieldChange) -> None:
        client = ClaudeSidecarClient(sidecar_config_from_settings(settings))
        payload = _field_payload(change)
        if not payload:
            return
        if change.update_prefix and change.prefix:
            try:
                async with cliproxy_prefix_write_lock(self._session):
                    await _reject_prefix_collision(client, change.prefix, skip_oauth_name=name)
                    await _send_auth_file_fields(client, name, payload)
            except PrefixWriteLockTimeout as exc:
                raise DashboardConflictError("Another CLIProxyAPI prefix update is in progress") from exc
            forget_remembered_prefixes()
            return
        await _send_auth_file_fields(client, name, payload)


async def _send_auth_file_fields(client: ClaudeSidecarClient, name: str, fields: Mapping[str, JsonValue]) -> None:
    try:
        await client.patch_auth_file_fields(name, fields)
    except ClaudeSidecarUnavailableError as exc:
        raise DashboardServiceUnavailableError(_sanitize_message(exc.message)) from exc
    except ClaudeSidecarError as exc:
        _raise_management_error(exc)


def _oauth_files(raw_files: Sequence[Mapping[str, JsonValue]]) -> list[Mapping[str, JsonValue]]:
    return [entry for entry in raw_files if not _runtime_only(entry)]


def _runtime_only(entry: Mapping[str, JsonValue]) -> bool:
    return entry.get("runtime_only") is True


def _audit_api_key(event: str, account: CliproxyApiKeyAccount) -> None:
    AuditService.log_async(
        event,
        details={
            "kind": account.kind,
            "index": account.index,
            "name": account.name,
            "base_url": account.base_url,
            "model_count": len(account.models),
        },
    )


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
        prefix=account.prefix,
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
    if change.update_weight:
        payload["weight"] = change.weight
    if change.update_priority:
        payload["priority"] = change.priority
    if change.update_excluded_models:
        payload["excluded_models"] = list(change.excluded_models or ())
    if change.update_prefix and change.prefix:
        payload["prefix"] = change.prefix
    return payload


async def _reject_prefix_collision(
    client: ClaudeSidecarClient,
    prefix: str,
    *,
    skip_oauth_name: str | None = None,
    skip_api_key: tuple[str, int] | None = None,
) -> None:
    """Refuse ``prefix`` when another OAuth file or API-key entry already has it."""

    others: list[str | None] = []
    for entry in await client.list_auth_files():
        name = entry.get("name")
        if isinstance(name, str) and skip_oauth_name is not None and name == skip_oauth_name:
            continue
        raw_prefix = entry.get("prefix")
        if isinstance(raw_prefix, str):
            others.append(raw_prefix)
    others.extend(await stored_api_key_prefixes(client, skip=skip_api_key))
    reject_duplicate_prefix(prefix, others)


def _fields_response(
    account: SidecarAuthQuota,
    raw: Mapping[str, JsonValue] | None,
    change: CredentialFieldChange,
) -> CliproxyCredentialFieldsResponse:
    prefix = change.prefix if change.update_prefix and change.prefix else account.prefix
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
    if change.update_weight:
        details["weight"] = change.weight
    if change.update_priority:
        details["priority"] = change.priority
    if change.update_excluded_models:
        details["excluded_models"] = list(change.excluded_models or ())
    if change.update_prefix:
        details["prefix"] = change.prefix
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
    return public_message(message)


def _require_oauth_provider(slug: str) -> OauthProvider:
    provider = oauth_provider(slug)
    if provider is None:
        raise DashboardBadRequestError("That provider cannot be signed in from the panel")
    return provider


async def _patch_disabled(client: ClaudeSidecarClient, account: SidecarAuthQuota, *, disabled: bool) -> None:
    try:
        await client.patch_auth_file_status(account.name, disabled=disabled, auth_index=account.auth_index)
    except ClaudeSidecarUnavailableError as exc:
        raise DashboardServiceUnavailableError(public_message(exc.message)) from exc
    except ClaudeSidecarError as exc:
        _raise_management_error(exc)


async def _management_call[T](
    client: ClaudeSidecarClient,
    call: Callable[[CliproxyManagement], Awaitable[T]],
) -> T:
    try:
        return await call(build_management(client))
    except ClaudeSidecarUnavailableError as exc:
        raise DashboardServiceUnavailableError(public_message(exc.message)) from exc
    except ClaudeSidecarError as exc:
        _raise_management_error(exc)


async def _upload_auth_file(client: ClaudeSidecarClient, name: str, body: bytes) -> None:
    try:
        await build_management(client).upload_auth_file(name, body)
    except ClaudeSidecarUnavailableError as exc:
        raise DashboardServiceUnavailableError(public_message(exc.message)) from exc
    except ClaudeSidecarError as exc:
        _raise_management_error(exc)


def _refresh_response(observation: RefreshObservation) -> CliproxyCredentialRefreshResponse:
    return CliproxyCredentialRefreshResponse(
        name=observation.name,
        status=observation.status,
        message=observation.message,
    )


def _delete_failed_message(message: str) -> str:
    detail = public_message(message)
    base = "The credential was turned off, but CLIProxyAPI did not delete it. It stays turned off."
    if not detail or detail in base:
        return base
    return f"{base} {detail}"


def _audit_delete(account: SidecarAuthQuota, *, deleted: bool, message: str | None) -> None:
    details: dict[str, str | bool] = {
        "credential_name": account.name,
        "provider": account.provider or "unknown",
        "disabled": True,
        "deleted": deleted,
    }
    if message:
        details["message"] = message
    AuditService.log_async("cliproxy_credential_deleted", details=details)


def _audit_upload(name: str, provider: str, prefix: str | None) -> None:
    details: dict[str, str | None] = {
        "credential_name": name,
        "provider": provider,
        "prefix": prefix,
    }
    AuditService.log_async("cliproxy_credential_uploaded", details=details)
