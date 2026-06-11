from __future__ import annotations

import asyncio
import contextlib
import importlib
import logging
from dataclasses import dataclass, field
from typing import Protocol, cast

from app.core.clients.claude_sidecar import (
    ClaudeSidecarClient,
    ClaudeSidecarError,
    ClaudeSidecarUnavailableError,
)
from app.core.config.settings import get_settings
from app.core.config.settings_cache import get_settings_cache
from app.db.session import get_background_session
from app.modules.claude_sidecar.usage_queue import parse_usage_queue_records
from app.modules.claude_sidecar.usage_repository import ClaudeSidecarUsageRepository
from app.modules.proxy.claude_sidecar_dispatch import sidecar_config_from_settings

logger = logging.getLogger(__name__)


class _LeaderElectionLike(Protocol):
    async def try_acquire(self) -> bool: ...


def _get_leader_election() -> _LeaderElectionLike:
    module = importlib.import_module("app.core.scheduling.leader_election")
    return cast(_LeaderElectionLike, module.get_leader_election())


@dataclass(slots=True)
class ClaudeSidecarUsageCollector:
    interval_seconds: float
    enabled: bool
    batch_size: int
    max_batches_per_tick: int = 10
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
            await self._collect_once()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue

    async def _collect_once(self) -> None:
        try:
            if not await _get_leader_election().try_acquire():
                return
            async with self._lock:
                await self._collect_locked()
        except Exception:
            logger.warning("Claude sidecar usage collector encountered unexpected error", exc_info=True)

    async def _collect_locked(self) -> None:
        try:
            settings_row = await get_settings_cache().get()
        except Exception:
            logger.warning("failed to load dashboard settings for Claude sidecar usage collection", exc_info=True)
            return

        if not settings_row.claude_sidecar_enabled:
            return
        if not settings_row.claude_sidecar_management_key_encrypted:
            return
        if not settings_row.claude_sidecar_usage_collection_enabled:
            return

        config = sidecar_config_from_settings(settings_row)
        if not config.management_key:
            return
        client = self._client_factory(config)
        await self._drain_queue(client, int(settings_row.claude_sidecar_usage_queue_batch_size))

    async def _drain_queue(self, client: ClaudeSidecarClient, batch_size: int) -> None:
        batch_size = max(1, batch_size)
        for _ in range(self.max_batches_per_tick):
            try:
                raw_records = await client.pop_usage_queue(batch_size)
            except ClaudeSidecarError as exc:
                if exc.status_code in (401, 403):
                    logger.warning("Claude sidecar usage queue unauthorized: %s", exc.message)
                elif isinstance(exc, ClaudeSidecarUnavailableError):
                    logger.warning("Claude sidecar usage queue unreachable: %s", exc.message)
                else:
                    logger.warning("Claude sidecar usage queue error: %s", exc.message)
                return
            records = parse_usage_queue_records(raw_records)
            if records:
                try:
                    async with get_background_session() as session:
                        repo = ClaudeSidecarUsageRepository(session)
                        await repo.insert_usage_events(records)
                except Exception:
                    logger.warning("failed to persist Claude sidecar usage records", exc_info=True)
            if len(raw_records) < batch_size:
                return


def build_claude_sidecar_usage_collector() -> ClaudeSidecarUsageCollector:
    settings = get_settings()
    return ClaudeSidecarUsageCollector(
        interval_seconds=max(1.0, float(settings.claude_sidecar_usage_poll_interval_seconds)),
        enabled=True,
        batch_size=max(1, int(settings.claude_sidecar_usage_queue_batch_size)),
    )
