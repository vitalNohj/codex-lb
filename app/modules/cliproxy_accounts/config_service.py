"""Guarded CLIProxyAPI config.yaml view, replace, and rollback.

Reads and writes go through the existing management client. The browser only
receives a redacted document. A confirmed replace snapshots the previous file
in codex-lb before the upload, and a failed upload puts that snapshot back so
a rejected write does not destroy the last rollback point.

The editor does not run unless the CLIProxyAPI integration is enabled, so a
default install never contacts CLIProxyAPI from these routes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clients.claude_sidecar import (
    ClaudeSidecarClient,
    ClaudeSidecarConfig,
    ClaudeSidecarError,
    ClaudeSidecarUnavailableError,
)
from app.core.clients.cliproxy_routing_config import (
    ROUTING_BOOL_FIELDS,
    CliproxyRoutingConfigError,
    apply_routing_bool_yaml,
)
from app.core.utils.request_id import get_request_id
from app.db.models import AuditLog, DashboardSettings
from app.modules.cliproxy_accounts.config_editor import (
    REDACTION_MARK,
    CliproxyConfigEditorError,
    CliproxyConfigPlaceholderError,
    CliproxyConfigYamlError,
    ConfigEdit,
    content_sha256,
    prepare_config_edit,
    redact_config_yaml,
    routing_flags,
)
from app.modules.cliproxy_accounts.config_repository import CliproxyConfigSnapshotRepository, StoredConfigSnapshot
from app.modules.cliproxy_accounts.config_schemas import (
    CliproxyConfigPreview,
    CliproxyConfigStatus,
    CliproxyConfigView,
)
from app.modules.cliproxy_accounts.config_write_lock import (
    CliproxyConfigWriteBusy,
    cliproxy_config_lock_key,
    cliproxy_config_write_lock,
)
from app.modules.proxy.claude_sidecar_dispatch import sidecar_config_from_settings
from app.modules.settings.repository import SettingsRepository

_AUDIT_REPLACE = "cliproxy_config_replace"
_AUDIT_ROLLBACK = "cliproxy_config_rollback"
_AUDIT_PATCH = "cliproxy_config_routing_patch"


class CliproxyConfigOperationError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class _ConfigTransport(Protocol):
    async def fetch_config_yaml(self) -> str: ...

    async def put_config_yaml(self, body: str) -> None: ...


type _ConfigClientFactory = Callable[[ClaudeSidecarConfig], _ConfigTransport]


@dataclass(frozen=True, slots=True)
class _OpenedConfig:
    settings: DashboardSettings
    current: str
    rollback_available: bool


class CliproxyConfigService:
    def __init__(
        self,
        settings_repository: SettingsRepository,
        snapshot_repository: CliproxyConfigSnapshotRepository,
        session: AsyncSession,
        client_factory: _ConfigClientFactory | None = None,
    ) -> None:
        self._settings_repository = settings_repository
        self._snapshots = snapshot_repository
        self._session = session
        self._client_factory = client_factory or ClaudeSidecarClient

    async def view(self) -> CliproxyConfigView:
        opened = await self._open()
        if isinstance(opened, CliproxyConfigView):
            return opened
        return _healthy_view(opened.current, rollback_available=opened.rollback_available)

    async def preview(self, yaml_text: str, expected_sha256: str) -> CliproxyConfigPreview:
        opened = await self._open()
        if isinstance(opened, CliproxyConfigView):
            return CliproxyConfigPreview(status=opened.status, message=opened.message)
        _require_current_sha(opened.current, expected_sha256)
        edit = _prepare(opened.current, yaml_text)
        return CliproxyConfigPreview(
            status="healthy",
            diff=edit.diff,
            changed=edit.changed,
            content_sha256=content_sha256(opened.current),
        )

    async def replace(self, yaml_text: str, expected_sha256: str, *, actor_ip: str | None) -> CliproxyConfigView:
        opened = await self._open()
        if isinstance(opened, CliproxyConfigView):
            return opened
        _require_current_sha(opened.current, expected_sha256)
        edit = _prepare(opened.current, yaml_text)
        if not edit.changed:
            return _healthy_view(opened.current, rollback_available=opened.rollback_available)
        await self._publish(
            opened,
            edit.restored,
            action="replace",
            audit_action=_AUDIT_REPLACE,
            actor_ip=actor_ip,
            details={
                "content_sha256_before": content_sha256(opened.current),
                "content_sha256_after": content_sha256(edit.restored),
                "bytes_before": len(opened.current.encode("utf-8")),
                "bytes_after": len(edit.restored.encode("utf-8")),
            },
        )
        return _healthy_view(edit.restored, rollback_available=True)

    async def rollback(self, *, actor_ip: str | None) -> CliproxyConfigView:
        opened = await self._open()
        if isinstance(opened, CliproxyConfigView):
            return opened
        snapshot = await self._snapshots.latest()
        if snapshot is None:
            raise CliproxyConfigOperationError(409, "nothing_to_rollback", "No CLIProxyAPI config snapshot to restore")
        if snapshot.yaml_text == opened.current:
            return _healthy_view(opened.current, rollback_available=True)
        await self._publish(
            opened,
            snapshot.yaml_text,
            action="rollback",
            audit_action=_AUDIT_ROLLBACK,
            actor_ip=actor_ip,
            details={
                "content_sha256_before": content_sha256(opened.current),
                "content_sha256_after": snapshot.content_sha256,
            },
        )
        return _healthy_view(snapshot.yaml_text, rollback_available=True)

    async def patch_routing_flag(
        self,
        field: str,
        enabled: bool,
        expected_sha256: str,
        *,
        actor_ip: str | None,
    ) -> CliproxyConfigView:
        if field not in ROUTING_BOOL_FIELDS:
            raise CliproxyConfigOperationError(404, "unknown_field", f"Unsupported config field: {field}")
        opened = await self._open()
        if isinstance(opened, CliproxyConfigView):
            return opened
        _require_current_sha(opened.current, expected_sha256)
        try:
            updated = apply_routing_bool_yaml(opened.current, field, enabled)
        except CliproxyRoutingConfigError as exc:
            raise CliproxyConfigOperationError(400, "invalid_routing", str(exc)) from exc
        if updated == opened.current:
            return _healthy_view(opened.current, rollback_available=opened.rollback_available)
        await self._publish(
            opened,
            updated,
            action="routing_patch",
            audit_action=_AUDIT_PATCH,
            actor_ip=actor_ip,
            details={
                "field": f"routing.{field}",
                "enabled": enabled,
                "content_sha256_before": content_sha256(opened.current),
                "content_sha256_after": content_sha256(updated),
            },
        )
        return _healthy_view(updated, rollback_available=True)

    async def _open(self) -> _OpenedConfig | CliproxyConfigView:
        settings = await self._settings_repository.get_or_create()
        rollback_available = await self._snapshots.has_snapshot()
        guarded = _guard(settings)
        if guarded is not None:
            status, message = guarded
            return CliproxyConfigView(status=status, message=message, rollback_available=rollback_available)
        client = self._client(settings)
        try:
            current = await client.fetch_config_yaml()
        except ClaudeSidecarUnavailableError:
            return CliproxyConfigView(
                status="unreachable",
                message="CLIProxyAPI is unreachable",
                rollback_available=rollback_available,
            )
        except ClaudeSidecarError as exc:
            return _upstream_view(exc, rollback_available=rollback_available)
        return _OpenedConfig(settings=settings, current=current, rollback_available=rollback_available)

    async def _publish(
        self,
        opened: _OpenedConfig,
        updated: str,
        *,
        action: str,
        audit_action: str,
        actor_ip: str | None,
        details: dict[str, str | int | bool],
    ) -> None:
        if REDACTION_MARK in updated:
            raise CliproxyConfigOperationError(
                400,
                "redacted_placeholder",
                "redacted placeholder cannot be written to the config file",
            )
        try:
            async with cliproxy_config_write_lock(
                cliproxy_config_lock_key(opened.settings.claude_sidecar_base_url),
                timeout=0,
            ):
                await self._upload(
                    opened,
                    updated,
                    action=action,
                    audit_action=audit_action,
                    actor_ip=actor_ip,
                    details=details,
                )
        except CliproxyConfigWriteBusy as exc:
            raise CliproxyConfigOperationError(
                409,
                "config_write_busy",
                "Another CLIProxyAPI config write is in progress",
            ) from exc

    async def _upload(
        self,
        opened: _OpenedConfig,
        updated: str,
        *,
        action: str,
        audit_action: str,
        actor_ip: str | None,
        details: dict[str, str | int | bool],
    ) -> None:
        client = self._client(opened.settings)
        try:
            again = await client.fetch_config_yaml()
        except ClaudeSidecarUnavailableError as exc:
            raise CliproxyConfigOperationError(503, "unreachable", "CLIProxyAPI is unreachable") from exc
        except ClaudeSidecarError as exc:
            raise _upstream_error(exc) from exc
        if again != opened.current:
            raise CliproxyConfigOperationError(
                409,
                "config_changed",
                "CLIProxyAPI config changed. Reload it and try again.",
            )
        previous = await self._snapshots.latest()
        await self._snapshots.store(opened.current, action=action)
        await self._session.commit()
        try:
            await client.put_config_yaml(updated)
        except ClaudeSidecarUnavailableError as exc:
            await self._restore_snapshot(previous)
            raise CliproxyConfigOperationError(503, "unreachable", "CLIProxyAPI is unreachable") from exc
        except ClaudeSidecarError as exc:
            await self._restore_snapshot(previous)
            raise _upstream_error(exc) from exc
        self._session.add(
            AuditLog(
                action=audit_action,
                actor_ip=actor_ip[:50] if actor_ip else None,
                details=json.dumps(details, sort_keys=True),
                request_id=get_request_id(),
            )
        )
        await self._session.commit()

    async def _restore_snapshot(self, previous: StoredConfigSnapshot | None) -> None:
        if previous is None:
            await self._snapshots.clear()
        else:
            await self._snapshots.store(previous.yaml_text, action=previous.action)
        await self._session.commit()

    def _client(self, settings: DashboardSettings) -> _ConfigTransport:
        return self._client_factory(sidecar_config_from_settings(settings))


def _prepare(current: str, submitted: str) -> ConfigEdit:
    try:
        return prepare_config_edit(current, submitted)
    except CliproxyConfigPlaceholderError as exc:
        raise CliproxyConfigOperationError(400, "redacted_placeholder", str(exc)) from exc
    except CliproxyConfigYamlError as exc:
        raise CliproxyConfigOperationError(400, "invalid_yaml", str(exc)) from exc
    except CliproxyConfigEditorError as exc:
        raise CliproxyConfigOperationError(400, "invalid_config", str(exc)) from exc


def _require_current_sha(current: str, expected_sha256: str) -> None:
    if content_sha256(current) != expected_sha256:
        raise CliproxyConfigOperationError(
            409,
            "config_changed",
            "CLIProxyAPI config changed. Reload it and try again.",
        )


def _guard(settings: DashboardSettings) -> tuple[CliproxyConfigStatus, str] | None:
    if not settings.claude_sidecar_enabled:
        return "disabled", "CLIProxyAPI integration is disabled"
    if not settings.claude_sidecar_management_key_encrypted:
        return "not_configured", "CLIProxyAPI management key is not configured"
    return None


def _healthy_view(text: str, *, rollback_available: bool) -> CliproxyConfigView:
    try:
        if text.strip():
            session_affinity, force_model_prefix = routing_flags(text)
            yaml_text = redact_config_yaml(text)
        else:
            session_affinity, force_model_prefix = False, False
            yaml_text = text
    except CliproxyConfigEditorError:
        return CliproxyConfigView(
            status="error",
            message="CLIProxyAPI config could not be read",
            rollback_available=rollback_available,
        )
    return CliproxyConfigView(
        status="healthy",
        yaml=yaml_text,
        content_sha256=content_sha256(text),
        session_affinity=session_affinity,
        force_model_prefix=force_model_prefix,
        rollback_available=rollback_available,
    )


def _upstream_view(exc: ClaudeSidecarError, *, rollback_available: bool) -> CliproxyConfigView:
    if exc.status_code in {401, 403}:
        return CliproxyConfigView(
            status="unauthorized",
            message="CLIProxyAPI management key was rejected",
            rollback_available=rollback_available,
        )
    return CliproxyConfigView(
        status="error",
        message="CLIProxyAPI config request failed",
        rollback_available=rollback_available,
    )


def _upstream_error(exc: ClaudeSidecarError) -> CliproxyConfigOperationError:
    if exc.status_code in {401, 403}:
        return CliproxyConfigOperationError(401, "unauthorized", "CLIProxyAPI management key was rejected")
    return CliproxyConfigOperationError(502, "upstream_error", "CLIProxyAPI rejected the config update")
