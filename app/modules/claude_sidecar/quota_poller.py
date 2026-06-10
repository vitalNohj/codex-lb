from __future__ import annotations

import asyncio
import contextlib
import importlib
import logging
from dataclasses import dataclass, field
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
from app.modules.claude_sidecar.quota import (
    SidecarQuotaSnapshot,
    parse_auth_files,
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
        snapshot = await _classify_poll_result(client)
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


async def _classify_poll_result(client: ClaudeSidecarClient) -> SidecarQuotaSnapshot:
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

    accounts = parse_auth_files(raw_files)
    return SidecarQuotaSnapshot(
        checked_at=now,
        status="healthy",
        message=None,
        accounts=tuple(accounts),
    )


def build_claude_sidecar_quota_poller() -> ClaudeSidecarQuotaPoller:
    settings = get_settings()
    interval = max(1.0, float(settings.claude_sidecar_quota_poll_interval_seconds))
    # Scheduler is always started; the per-poll gate ensures we no-op until the
    # operator configures both the sidecar and a Management API key.
    return ClaudeSidecarQuotaPoller(
        interval_seconds=interval,
        enabled=True,
    )
