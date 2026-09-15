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
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol, TypeVar, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.core.utils.time import utcnow
from app.db.models import FreeModelDiscoveryRunItem
from app.db.session import get_background_session
from app.modules.free_model_discovery.pacing import ProviderPacer
from app.modules.free_model_discovery.probe import (
    ChatCompletionClient,
    ProbeResult,
    probe_model,
    redact_provider_text,
)
from app.modules.free_model_discovery.repository import FreeModelDiscoveryRepository
from app.modules.free_model_discovery.schemas import FREE_MODEL_PROVIDERS, FreeModelProvider
from app.modules.free_model_discovery.service import FreeModelDiscoveryService, provider_access
from app.modules.proxy.openrouter_sidecar_dispatch import openrouter_sidecar_config_from_settings
from app.modules.proxy.orcarouter_sidecar_dispatch import orcarouter_sidecar_config_from_settings
from app.modules.settings.repository import SettingsRepository

logger = logging.getLogger(__name__)


async def _configured_provider_api_keys(session: AsyncSession) -> tuple[str | None, ...]:
    """Every provider credential discovery could have used, for redaction only.

    Read on the failure path, where the exception may carry upstream text that
    echoed a key. Never raises: redacting against no key is a weaker guarantee
    than redacting against the real ones, but it must not stop the run from
    being marked failed - leaving the run ``running`` forever is the worse
    outcome and the bug this path exists to prevent.
    """

    try:
        settings = await SettingsRepository(session).get_or_create()
        return (
            openrouter_sidecar_config_from_settings(settings).api_key,
            orcarouter_sidecar_config_from_settings(settings).api_key,
        )
    except Exception:
        logger.warning("Could not resolve provider keys to redact a discovery failure", exc_info=True)
        return ()


# Poll cadence when idle. A ``wake()`` short-circuits it.
_IDLE_POLL_SECONDS = 30.0
# Re-check cancel/deadline at least this often while waiting out a long pace.
_WAIT_SLICE_SECONDS = 5.0
# How long an inconclusive item is parked before it is eligible again. The
# provider pacer still bounds the gap between probes; this only orders the
# queue so the next item gets its turn before a retry.
_INCONCLUSIVE_REQUEUE = timedelta(minutes=2)
# Cap on the operator-visible failure text persisted to ``error_message``.
_RUN_ERROR_MAX_CHARS = 255

_T = TypeVar("_T")


def _run_error_message(exc: BaseException, *, api_keys: Sequence[str | None] = ()) -> str:
    """Operator-facing text for a run that died of an unexpected internal error.

    Deliberately the exception type plus its own message, never a traceback and
    never settings, headers or prompts: this string is served by the run API and
    rendered in the dashboard. Full diagnostics stay in the logs, where
    ``logger.exception`` already put them.

    An exception raised inside a provider client can still carry upstream text
    that echoed a credential, so the message is redacted against EVERY
    configured provider key, not just the unconditional ``Bearer``/``sk-orca-``
    patterns. Those patterns alone would miss a bare OpenRouter ``sk-`` key,
    which has no distinguishing prefix - matching the configured value exactly
    is what closes that gap. Redaction is applied per key because the sanitizer
    takes one credential at a time.
    """

    detail = str(exc).strip()
    described = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
    redacted = f"discovery run failed: {described}"
    for api_key in api_keys:
        redacted = redact_provider_text(redacted, api_key=api_key)
    # A final unconditional pass, so text is still sanitized when no key could
    # be resolved (e.g. the settings read itself is what failed).
    redacted = " ".join(redact_provider_text(redacted, api_key=None).split())
    if len(redacted) <= _RUN_ERROR_MAX_CHARS:
        return redacted
    return redacted[: _RUN_ERROR_MAX_CHARS - 3] + "..."


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


async def _gather_owned(tasks: list[asyncio.Task[None]]) -> None:
    """Await provider tasks, leaving none running when this returns or raises.

    A bare ``gather`` propagates the first exception while its siblings keep
    running. The driver's caller then releases the leader lock, so those
    detached tasks keep probing while the next tick can start a second driver
    for the same run - duplicate load on rate-limited providers. The
    single-active index guards run *creation* and does not cover this.

    So: wait for the first failure, then cancel and await the rest before
    returning. Cancellation of this coroutine propagates the same way, which is
    what makes shutdown leave nothing behind. The first exception is re-raised
    so the existing error handling is unchanged; waiting for a possibly
    multi-hour sibling instead would defeat the point.
    """

    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    except asyncio.CancelledError:
        await _cancel_and_await(tasks)
        raise
    if pending:
        await _cancel_and_await(list(pending))
    for task in done:
        if not task.cancelled() and task.exception() is not None:
            raise cast(BaseException, task.exception())


async def _cancel_and_await(tasks: list[asyncio.Task[None]]) -> None:
    for task in tasks:
        task.cancel()
    # ``return_exceptions`` so one task's failure cannot abandon the others
    # mid-cleanup; this is the drain, not the place to surface errors.
    await asyncio.gather(*tasks, return_exceptions=True)


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
            run_id: str | None = None
            try:
                async with get_background_session() as session:
                    run = await FreeModelDiscoveryRepository(session).get_active_run()
                    run_id = run.id if run is not None else None
                if run_id is None:
                    return
                await self.drive_run(run_id)
            except asyncio.CancelledError:
                # Shutdown/cancellation is not a run failure: the run stays
                # ``running`` so the next boot resumes it, exactly like
                # ``_finalize`` does when ``_stop`` is set.
                raise
            except Exception as exc:
                logger.exception("Free model discovery runner failed")
                if run_id is not None:
                    await self._fail_run(run_id, exc)

    async def _fail_run(self, run_id: str, exc: BaseException) -> None:
        """Record an unexpected driver error as a terminal ``failed`` run.

        Without this the broad ``except`` above only logged, so a run whose
        driver could never reach its first probe stayed ``running`` forever
        with ``error_message`` NULL - the dashboard kept rendering a dead run
        as Running, and the single-active index blocked every later run.

        Provider-specific and transport failures never reach here: ``probe_model``
        turns them into ``inconclusive`` results the queue retries. Anything that
        escapes to this handler is an unexpected internal failure, which is why
        it is terminal rather than retried.

        Persisting the row must never itself wedge the loop, so its own failure
        is logged and swallowed; the next tick retries.
        """

        try:
            async with get_background_session() as session:
                # Resolve the configured credentials while settings are still
                # bound, so the failure text can be redacted against the real
                # keys rather than pattern-guessed.
                api_keys = await _configured_provider_api_keys(session)
                await FreeModelDiscoveryRepository(session).fail_run(
                    run_id, finished_at=utcnow(), error_message=_run_error_message(exc, api_keys=api_keys)
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to record a failed free model discovery run run_id=%s", run_id)

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
            # Resolve provider access HERE, while ``settings`` is still bound to
            # a live session. ``provider_access`` reads ORM columns, and this
            # block's exit expires the instance, so reading it afterwards raised
            # ``DetachedInstanceError`` on every tick - before any provider
            # client existed, so discovery never issued a single probe.
            # ``ProviderAccess`` is a frozen dataclass of plain values and an
            # already-constructed client, so it stays valid past this boundary
            # and no transaction is held open across the probe network calls.
            accesses = {
                provider: provider_access(settings, provider)
                for provider in FREE_MODEL_PROVIDERS
                if provider in providers_present
            }

        _progress[run_id] = {}
        try:
            tasks: list[asyncio.Task[None]] = []
            for provider in FREE_MODEL_PROVIDERS:
                access = accesses.get(provider)
                if access is None:
                    continue
                if access.client is None:
                    await self._park_provider(run_id, provider, reason=access.message or "provider unavailable")
                    continue
                pacer = ProviderPacer(floor_seconds=floor, cap_seconds=cap)
                tasks.append(
                    asyncio.create_task(
                        self._drive_provider(
                            run_id,
                            provider,
                            access.client,
                            pacer,
                            max_attempts,
                            deadline,
                            api_key=access.api_key,
                        ),
                        name=f"free-model-discovery-{provider}",
                    )
                )
            if tasks:
                await _gather_owned(tasks)
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
        api_key: str | None = None,
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
                result = await probe_model(client, item.model_id, api_key=api_key)
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
            finished = await repository.finish_run(run_id, status=status, finished_at=now)
        if not finished:
            # Another writer ended this run between the read above and the
            # guarded write; its terminal state is the truthful one.
            logger.info("Free model discovery run was already finished by another writer run_id=%s", run_id)
            return
        logger.info("Free model discovery run finished run_id=%s status=%s", run_id, status)


_runner: FreeModelDiscoveryRunner | None = None


def discovery_execution_enabled() -> bool:
    """Whether anything will actually drive a discovery run.

    The single authority for both the runner lifecycle and the start API, so
    the two cannot disagree. Without it the API could accept a run (201) that
    no loop ever drives, leaving a permanently ``running`` row - which, with the
    single-active index, then blocks every later run.

    Deliberately the same global scheduler switch the runner already uses, not
    a new setting: discovery is an automation, and an operator who turned
    automations off should not get a new knob to discover.
    """

    return bool(get_settings().automations_scheduler_enabled)


def build_free_model_discovery_runner() -> FreeModelDiscoveryRunner:
    global _runner
    _runner = FreeModelDiscoveryRunner(enabled=discovery_execution_enabled())
    return _runner


def wake_free_model_discovery_runner() -> None:
    if _runner is not None:
        _runner.wake()
