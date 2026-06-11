from __future__ import annotations

import asyncio
import contextlib
import importlib
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Protocol, cast

from app.core.clients.claude_sidecar import (
    ClaudeSidecarClient,
    ClaudeSidecarError,
    ClaudeSidecarUnavailableError,
)
from app.core.config.settings import get_settings
from app.core.config.settings_cache import get_settings_cache
from app.db.session import get_background_session
from app.modules.claude_sidecar.oauth_usage import (
    ClaudeOAuthUsageError,
    fetch_claude_oauth_usage,
    load_claude_oauth_credential,
)
from app.modules.claude_sidecar.quota import (
    SidecarAuthQuota,
    SidecarOAuthUsage,
    SidecarQuotaSnapshot,
    parse_auth_files,
    snapshot_from_json,
    snapshot_to_json,
)
from app.modules.proxy.claude_sidecar_dispatch import sidecar_config_from_settings
from app.modules.settings.repository import SettingsRepository

logger = logging.getLogger(__name__)


class _LeaderElectionLike(Protocol):
    async def try_acquire(self) -> bool: ...


def _get_leader_election() -> _LeaderElectionLike:
    module = importlib.import_module("app.core.scheduling.leader_election")
    return cast(_LeaderElectionLike, module.get_leader_election())


@dataclass(slots=True)
class ClaudeSidecarQuotaPoller:
    """Polls CLIProxyAPI's management auth-files endpoint and stores the snapshot."""

    interval_seconds: float
    enabled: bool
    _task: asyncio.Task[None] | None = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _client_factory: type[ClaudeSidecarClient] = ClaudeSidecarClient

    async def start(self) -> None:
        if not self.enabled:
            return
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            await self._poll_once()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue

    async def _poll_once(self) -> None:
        try:
            if not await _get_leader_election().try_acquire():
                return
            async with self._lock:
                await self._poll_locked()
        except Exception:
            logger.warning("Claude sidecar quota poll loop encountered unexpected error", exc_info=True)

    async def _poll_locked(self) -> None:
        try:
            settings_row = await get_settings_cache().get()
        except Exception:
            logger.warning("failed to load dashboard settings for Claude sidecar quota poll", exc_info=True)
            return

        if not settings_row.claude_sidecar_enabled:
            return
        if not settings_row.claude_sidecar_management_key_encrypted:
            return

        config = sidecar_config_from_settings(settings_row)
        if not config.management_key:
            return
        client = self._client_factory(config)
        previous_snapshot = snapshot_from_json(settings_row.claude_sidecar_quota_state_json)
        snapshot = await _classify_poll_result(client, previous_snapshot)
        await self._persist_snapshot(snapshot)

    async def _persist_snapshot(self, snapshot: SidecarQuotaSnapshot) -> None:
        try:
            async with get_background_session() as session:
                repo = SettingsRepository(session)
                await repo.update(
                    claude_sidecar_quota_state_json=snapshot_to_json(snapshot),
                    claude_sidecar_quota_checked_at=snapshot.checked_at,
                )
            await get_settings_cache().invalidate()
        except Exception:
            logger.warning("failed to persist Claude sidecar quota snapshot", exc_info=True)


async def _classify_poll_result(
    client: ClaudeSidecarClient,
    previous_snapshot: SidecarQuotaSnapshot | None = None,
) -> SidecarQuotaSnapshot:
    now = datetime.now(timezone.utc)
    try:
        raw_files = await client.list_auth_files()
    except ClaudeSidecarError as exc:
        if exc.status_code in (401, 403):
            return SidecarQuotaSnapshot(
                checked_at=now,
                status="unauthorized",
                message=exc.message,
                accounts=(),
            )
        if isinstance(exc, ClaudeSidecarUnavailableError):
            return SidecarQuotaSnapshot(
                checked_at=now,
                status="unreachable",
                message=exc.message,
                accounts=(),
            )
        return SidecarQuotaSnapshot(
            checked_at=now,
            status="error",
            message=exc.message,
            accounts=(),
        )
    except Exception as exc:
        return SidecarQuotaSnapshot(
            checked_at=now,
            status="error",
            message=str(exc) or exc.__class__.__name__,
            accounts=(),
        )

    accounts = await _attach_oauth_usage(parse_auth_files(raw_files), previous_snapshot)
    return SidecarQuotaSnapshot(
        checked_at=now,
        status="healthy",
        message=None,
        accounts=tuple(accounts),
    )


async def _attach_oauth_usage(
    accounts: list[SidecarAuthQuota],
    previous_snapshot: SidecarQuotaSnapshot | None = None,
) -> list[SidecarAuthQuota]:
    previous_usage = _previous_oauth_usage_by_key(previous_snapshot)
    enriched: list[SidecarAuthQuota] = []
    for account in accounts:
        usage = None
        credential = await load_claude_oauth_credential(account.credential_path)
        if credential is not None:
            try:
                usage = await fetch_claude_oauth_usage(credential)
            except ClaudeOAuthUsageError as exc:
                logger.debug(
                    "failed to fetch Claude OAuth usage for %s: %s",
                    account.email or account.auth_index or account.name,
                    exc,
                )
        if usage is None:
            # Anthropic's OAuth usage endpoint intermittently rate-limits
            # (HTTP 429); keep the last-known buckets so the dashboard's
            # 5h/weekly bars do not flap to "Unavailable" between polls.
            usage = previous_usage.get(_auth_identity_key(account))
        enriched.append(replace(account, oauth_usage=usage))
    return enriched


def _previous_oauth_usage_by_key(
    snapshot: SidecarQuotaSnapshot | None,
) -> dict[str | None, SidecarOAuthUsage]:
    if snapshot is None:
        return {}
    usage_by_key: dict[str | None, SidecarOAuthUsage] = {}
    for account in snapshot.accounts:
        key = _auth_identity_key(account)
        if key is not None and account.oauth_usage is not None:
            usage_by_key[key] = account.oauth_usage
    return usage_by_key


def _auth_identity_key(account: SidecarAuthQuota) -> str | None:
    if account.auth_index:
        return f"auth:{account.auth_index}"
    if account.email:
        return f"email:{account.email.lower()}"
    if account.name:
        return f"name:{account.name.lower()}"
    return None


def build_claude_sidecar_quota_poller() -> ClaudeSidecarQuotaPoller:
    settings = get_settings()
    interval = max(1.0, float(settings.claude_sidecar_quota_poll_interval_seconds))
    # Scheduler is always started; the per-poll gate ensures we no-op until the
    # operator configures both the sidecar and a Management API key.
    return ClaudeSidecarQuotaPoller(
        interval_seconds=interval,
        enabled=True,
    )
