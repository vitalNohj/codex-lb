from __future__ import annotations

import asyncio
from collections import defaultdict

from app.core.clients.claude_sidecar import ClaudeSidecarClient, ClaudeSidecarError, ClaudeSidecarUnavailableError
from app.db.models import DashboardSettings
from app.modules.claude_sidecar.quota import SidecarAuthQuota, dashboard_auth_status, parse_auth_files
from app.modules.cliproxy_accounts.schemas import (
    CliproxyAccountsResponse,
    CliproxyAccountsStatus,
    CliproxyCredential,
    CliproxyProviderCredentials,
)
from app.modules.proxy.claude_sidecar_dispatch import sidecar_config_from_settings
from app.modules.settings.repository import SettingsRepository


class CliproxyAccountsService:
    """List CLIProxyAPI credentials. This service never mutates the sidecar."""

    def __init__(self, settings_repository: SettingsRepository) -> None:
        self._settings_repository = settings_repository

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
        credentials = await asyncio.gather(*(_credential(client, account) for account in accounts))
        grouped: dict[str, list[CliproxyCredential]] = defaultdict(list)
        for credential in credentials:
            grouped[credential.provider].append(credential)
        providers = [
            CliproxyProviderCredentials(provider=name, credentials=sorted(grouped[name], key=_credential_sort_key))
            for name in sorted(grouped)
        ]
        return CliproxyAccountsResponse(status="healthy", providers=providers)


def _inventory_guard(settings: DashboardSettings) -> tuple[CliproxyAccountsStatus, str] | None:
    base_url = (settings.claude_sidecar_base_url or "").strip()
    if not base_url:
        return "not_configured", "CLIProxyAPI base URL is not configured"
    if not settings.claude_sidecar_management_key_encrypted:
        return "not_configured", "CLIProxyAPI management key is not configured"
    return None


async def _credential(client: ClaudeSidecarClient, account: SidecarAuthQuota) -> CliproxyCredential:
    models, models_error = await _models_for(client, account.name)
    provider = (account.provider or "unknown").strip().lower() or "unknown"
    return CliproxyCredential(
        name=account.name,
        auth_index=account.auth_index,
        email=account.email,
        provider=provider,
        health=_credential_health(account),
        disabled=account.disabled,
        unavailable=account.unavailable,
        quota_exceeded=account.quota_exceeded,
        prefix=account.prefix,
        models=models,
        models_error=models_error,
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


def _credential_health(account: SidecarAuthQuota) -> str:
    if account.disabled:
        return "paused"
    mapped = dashboard_auth_status(account)
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


def _sanitize_message(message: str) -> str:
    return message.replace("Bearer ", "Bearer [redacted]")
