"""Background driver for free-model discovery runs.

One process-level runner. ``start()`` at lifespan boot resumes any run that
was in flight before a restart. ``wake()`` after ``start_run`` begins driving
the new run without waiting for the poll tick. Inside a run, each enabled
provider gets its own paced loop so OpenRouter and OrcaRouter advance
independently but never overlap on the same provider.

The runner is leader-gated like the other singleton schedulers so two
replicas sharing a database never probe the same run concurrently.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol, TypeVar, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.core.utils.time import utcnow
from app.db.models import FreeModelDiscoveryRunItem
from app.db.session import get_background_session
from app.modules.free_model_discovery.pacing import ProviderPacer
from app.modules.free_model_discovery.probe import ChatCompletionClient, ProbeResult, probe_model
from app.modules.free_model_discovery.repository import FreeModelDiscoveryRepository
from app.modules.free_model_discovery.schemas import FREE_MODEL_PROVIDERS, FreeModelProvider
from app.modules.free_model_discovery.service import FreeModelDiscoveryService, provider_access
from app.modules.settings.repository import SettingsRepository

logger = logging.getLogger(__name__)

# Poll cadence when idle. A ``wake()`` short-circuits it.
_IDLE_POLL_SECONDS = 30.0
# Re-check cancel/deadline at least this often while waiting out a long pace.
_WAIT_SLICE_SECONDS = 5.0
# How long an inconclusive item is parked before it is eligible again. The
# provider pacer still bounds the gap between probes; this only orders the
# queue so the next item gets its turn before a retry.
_INCONCLUSIVE_REQUEUE = timedelta(minutes=2)

_T = TypeVar("_T")


class _LeaderElectionLike(Protocol):
    async def run_if_leader(self, fn: Callable[[], Awaitable[_T]]) -> _T | None: ...


def _get_leader_election() -> _LeaderElectionLike:
    module = importlib.import_module("app.core.scheduling.leader_election")
    return cast(_LeaderElectionLike, module.get_leader_election())


@dataclass(slots=True)
class ProviderProgress:
    current_interval_seconds: float
    next_probe_at: datetime | None


# run_id -> provider -> live pacing state, for the run view. Process-local by
# design: it only describes what this runner is doing right now.
_progress: dict[str, dict[str, ProviderProgress]] = {}


def get_runner_progress(run_id: str) -> dict[str, ProviderProgress]:
    return dict(_progress.get(run_id, {}))


@dataclass(slots=True)
class FreeModelDiscoveryRunner:
    enabled: bool
    idle_poll_seconds: float = _IDLE_POLL_SECONDS
    _task: asyncio.Task[None] | None = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _wake: asyncio.Event = field(default_factory=asyncio.Event)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def start(self) -> None:
        if not self.enabled:
            return
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop(), name="free-model-discovery-runner")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop.set()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    def wake(self) -> None:
        self._wake.set()

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            await self._drive_once()
            if self._stop.is_set():
                return
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self.idle_poll_seconds)

    async def _drive_once(self) -> None:
        await _get_leader_election().run_if_leader(self._drive_as_leader)

    async def _drive_as_leader(self) -> None:
        async with self._lock:
            try:
                async with get_background_session() as session:
                    run = await FreeModelDiscoveryRepository(session).get_active_run()
                    run_id = run.id if run is not None else None
                if run_id is None:
                    return
                await self.drive_run(run_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Free model discovery runner failed")

    async def drive_run(self, run_id: str) -> None:
        """Drive one run to a terminal state. Each provider queue runs in its
        own task; the run finishes when every queue drains, the operator
        cancels, or the deadline passes."""

        async with get_background_session() as session:
            repository = FreeModelDiscoveryRepository(session)
            run = await repository.get_run(run_id)
            if run is None or run.status != "running":
                return
            settings = await SettingsRepository(session).get_or_create()
            providers_present = {item.provider for item in await repository.list_items(run_id)}
            floor = run.pacing_floor_seconds
            cap = run.pacing_cap_seconds
            max_attempts = run.max_attempts_per_item
            deadline = run.deadline_at

        _progress[run_id] = {}
        try:
            tasks: list[asyncio.Task[None]] = []
            for provider in FREE_MODEL_PROVIDERS:
                if provider not in providers_present:
                    continue
                access = provider_access(settings, provider)
                if access.client is None:
                    await self._park_provider(run_id, provider, reason=access.message or "provider unavailable")
                    continue
                pacer = ProviderPacer(floor_seconds=floor, cap_seconds=cap)
                tasks.append(
                    asyncio.create_task(
                        self._drive_provider(run_id, provider, access.client, pacer, max_attempts, deadline),
                        name=f"free-model-discovery-{provider}",
                    )
                )
            if tasks:
                await asyncio.gather(*tasks)
            await self._finalize(run_id)
        finally:
            _progress.pop(run_id, None)

    async def _park_provider(self, run_id: str, provider: str, *, reason: str) -> None:
        """Provider cannot be probed at all (disabled or no key): every one of
        its queued items is unresolved for this run."""

        now = utcnow()
        async with get_background_session() as session:
            repository = FreeModelDiscoveryRepository(session)
            while True:
                item = await repository.next_queued_item(run_id, provider)
                if item is None:
                    return
                await repository.mark_unresolved(item, resolved_at=now, outcome=f"skipped: {reason}")

    async def _drive_provider(
        self,
        run_id: str,
        provider: FreeModelProvider,
        client: ChatCompletionClient,
        pacer: ProviderPacer,
        max_attempts: int,
        deadline: datetime,
    ) -> None:
        wait_seconds = 0.0
        while not self._stop.is_set():
            if wait_seconds > 0:
                _progress.setdefault(run_id, {})[provider] = ProviderProgress(
                    current_interval_seconds=pacer.current_seconds,
                    next_probe_at=utcnow() + timedelta(seconds=wait_seconds),
                )
                if not await self._wait(wait_seconds, run_id, deadline):
                    return
            async with get_background_session() as session:
                repository = FreeModelDiscoveryRepository(session)
                if await self._should_halt(repository, run_id, deadline):
                    return
                item = await repository.next_queued_item(run_id, provider)
                if item is None:
                    return
                now = utcnow()
                if item.next_attempt_at is not None and item.next_attempt_at > now:
                    # Whole queue is parked: sleep until the earliest is due.
                    wait_seconds = max(_WAIT_SLICE_SECONDS, (item.next_attempt_at - now).total_seconds())
                    continue
                _progress.setdefault(run_id, {})[provider] = ProviderProgress(
                    current_interval_seconds=pacer.current_seconds, next_probe_at=None
                )
                result = await probe_model(client, item.model_id)
                wait_seconds = await self._apply_result(session, repository, item, result, pacer, max_attempts)

    async def _apply_result(
        self,
        session: AsyncSession,
        repository: FreeModelDiscoveryRepository,
        item: FreeModelDiscoveryRunItem,
        result: ProbeResult,
        pacer: ProviderPacer,
        max_attempts: int,
    ) -> float:
        now = utcnow()
        if result.verdict == "inconclusive":
            if item.attempts + 1 >= max_attempts:
                await repository.mark_unresolved(
                    item,
                    resolved_at=now,
                    outcome=f"gave up after {max_attempts} attempts: {result.outcome}",
                )
            else:
                await repository.record_inconclusive(
                    item,
                    attempted_at=now,
                    next_attempt_at=now + _INCONCLUSIVE_REQUEUE,
                    http_status=result.http_status,
                    outcome=result.outcome,
                )
            if result.rate_limited:
                return pacer.on_rate_limited(result.retry_after_seconds)
            return pacer.on_inconclusive()

        added = False
        if result.verdict == "passed":
            try:
                added = await FreeModelDiscoveryService(session).pin_full_model(
                    cast(FreeModelProvider, item.provider), item.model_id
                )
            except Exception:
                logger.exception(
                    "Failed to pin discovered free model provider=%s model=%s", item.provider, item.model_id
                )
        await repository.record_verdict(
            item,
            verdict=result.verdict,
            attempted_at=now,
            http_status=result.http_status,
            outcome=result.outcome,
            content_chars=result.content_chars,
            content_ok_match=result.content_ok_match,
            reasoning_chars=result.reasoning_chars,
            added_to_full_models=added,
        )
        return pacer.on_verdict()

    async def _should_halt(self, repository: FreeModelDiscoveryRepository, run_id: str, deadline: datetime) -> bool:
        if self._stop.is_set():
            return True
        if utcnow() >= deadline:
            return True
        return await repository.is_cancel_requested(run_id)

    async def _wait(self, seconds: float, run_id: str, deadline: datetime) -> bool:
        """Sleep in slices so cancel and deadline are honoured promptly.
        Returns False when the loop should exit."""

        remaining = seconds
        while remaining > 0:
            if self._stop.is_set() or utcnow() >= deadline:
                return False
            slice_seconds = min(_WAIT_SLICE_SECONDS, remaining)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=slice_seconds)
                return False
            remaining -= slice_seconds
            async with get_background_session() as session:
                if await FreeModelDiscoveryRepository(session).is_cancel_requested(run_id):
                    return False
        return True

    async def _finalize(self, run_id: str) -> None:
        if self._stop.is_set():
            # Process shutdown: leave the run ``running`` so the next boot resumes it.
            return
        now = utcnow()
        async with get_background_session() as session:
            repository = FreeModelDiscoveryRepository(session)
            run = await repository.get_run(run_id)
            if run is None or run.status != "running":
                return
            if run.cancel_requested:
                status = "cancelled"
            elif now >= run.deadline_at:
                status = "expired"
            else:
                status = "completed"
            await repository.finish_run(run_id, status=status, finished_at=now)
        logger.info("Free model discovery run finished run_id=%s status=%s", run_id, status)


_runner: FreeModelDiscoveryRunner | None = None


def build_free_model_discovery_runner() -> FreeModelDiscoveryRunner:
    global _runner
    settings = get_settings()
    _runner = FreeModelDiscoveryRunner(enabled=settings.automations_scheduler_enabled)
    return _runner


def wake_free_model_discovery_runner() -> None:
    if _runner is not None:
        _runner.wake()
