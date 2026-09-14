"""OpenCode Go quota service: freshness, single-flight, and honest failure.

Design constraints, each deliberate:

- **On demand, never polled.** There is no background task. A disabled or
  unconfigured integration therefore issues exactly zero upstream requests,
  which a poller gated on settings could not guarantee across a settings race.
- **Never blocks inference.** Nothing on the proxy dispatch path reaches this
  module; it is only reached from the dashboard endpoint.
- **Failure never masquerades as data.** A failed refresh returns the previous
  values marked ``stale`` with a reason, or ``unavailable`` - never zero usage
  and never full quota.
- **Last-good is in-process only.** No new table, no new secret. A restart
  yields ``unavailable``, which is honest, rather than persisted numbers of
  unknown age.
- **Cache isolation by construction.** The single cache entry is keyed by the
  whole frozen config, so changing the API key (or base URL, or enablement)
  replaces the entry wholesale and a new subscription can never read the old
  one's numbers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.clients.opencode_go import (
    OpenCodeGoClient,
    OpenCodeGoConfig,
    OpenCodeGoError,
    OpenCodeGoUnavailableError,
    sanitize_opencode_go_message,
)
from app.core.usage.opencode_go_quota import (
    OpenCodeGoQuota,
    OpenCodeGoQuotaParseError,
    parse_opencode_go_usage,
)
from app.core.utils.shared_future import wait_on_shared_future
from app.modules.opencode_go.backend_seam import (
    build_request_headers,
    quota_config_from_settings,
)
from app.modules.opencode_go.schemas import (
    OpenCodeGoQuotaResponse,
    OpenCodeGoQuotaStatus,
    OpenCodeGoQuotaWindowResponse,
)
from app.modules.settings.repository import SettingsRepository

logger = logging.getLogger(__name__)

#: Builds the upstream client. Keyword-only ``header_builder`` so a test double
#: can accept it without depending on the backend header helper.
_ClientFactory = Callable[..., OpenCodeGoClient]

DEFAULT_QUOTA_TTL_SECONDS = 60.0
# A failed refresh is remembered briefly so a dead endpoint cannot make every
# dashboard load pay another timeout. Shorter than the success TTL so recovery
# is quick. Mirrors the failure-TTL pattern in the reviewed Python prior art.
DEFAULT_FAILURE_TTL_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class _CachedQuota:
    config: OpenCodeGoConfig
    quota: OpenCodeGoQuota
    checked_at: datetime
    fetched_monotonic: float


@dataclass(frozen=True, slots=True)
class _CachedFailure:
    config: OpenCodeGoConfig
    status: OpenCodeGoQuotaStatus
    message: str
    failed_monotonic: float


class OpenCodeGoQuotaCache:
    """Single-entry TTL cache with single-flight and last-good retention.

    One entry, not a dict: the entry is keyed by the full config, so there is
    never more than one subscription's data resident, and a config change
    evicts both the numbers and the in-flight request that was fetching them.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_QUOTA_TTL_SECONDS,
        failure_ttl_seconds: float = DEFAULT_FAILURE_TTL_SECONDS,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._failure_ttl_seconds = failure_ttl_seconds
        self._success: _CachedQuota | None = None
        self._failure: _CachedFailure | None = None
        # A cache-owned task, so no individual caller's cancellation can kill
        # the request the other waiters are still depending on.
        self._inflight: asyncio.Task[_CachedQuota] | None = None
        # Bumped by every ``reset()``. A producer captures the generation it
        # started in; a write carrying a stale generation is discarded. Without
        # this, a fetch still in flight across a settings change would later
        # repopulate the cache with state derived from the *old* credential,
        # resurrecting exactly what the operator just invalidated.
        self._generation = 0
        # Producer task id -> the generation it started in.
        self._producer_generations: dict[int, int] = {}
        self._inflight_config: OpenCodeGoConfig | None = None
        self._lock = asyncio.Lock()

    def reset(self) -> None:
        """Drop all cached state (settings change, test isolation).

        Bumping the generation is what makes the invalidation *permanent*:
        detaching the in-flight task alone would not stop its closure from
        calling ``record_success``/``record_failure`` later and repopulating
        credential-derived state that was just dropped.

        The task is deliberately not cancelled here. Cancelling it would also
        cancel callers still legitimately waiting on it; they are allowed to
        receive the in-flight answer they asked for, while the *cache* refuses
        to retain anything derived from it.
        """
        self._generation += 1
        self._success = None
        self._failure = None
        self._inflight = None
        self._inflight_config = None

    def last_good(self, config: OpenCodeGoConfig) -> _CachedQuota | None:
        """Previous values for *this exact config*, whatever their age.

        Config equality is what stops a re-keyed subscription from inheriting
        the previous key's numbers as "stale" data.
        """
        cached = self._success
        if cached is None or cached.config != config:
            return None
        return cached

    def fresh(self, config: OpenCodeGoConfig, *, now: float) -> _CachedQuota | None:
        cached = self.last_good(config)
        if cached is None:
            return None
        if now - cached.fetched_monotonic >= self._ttl_seconds:
            return None
        return cached

    def recent_failure(self, config: OpenCodeGoConfig, *, now: float) -> _CachedFailure | None:
        failure = self._failure
        if failure is None or failure.config != config:
            return None
        if now - failure.failed_monotonic >= self._failure_ttl_seconds:
            return None
        return failure

    def record_failure(
        self,
        config: OpenCodeGoConfig,
        status: OpenCodeGoQuotaStatus,
        message: str,
        *,
        generation: int | None = None,
    ) -> None:
        """Remember a failure, unless it belongs to an invalidated generation.

        ``generation`` defaults to the generation of the producer running in the
        current task, so a write from a stale producer is rejected even when the
        caller does not pass one explicitly. Guarding by default rather than
        opt-in matters: a future call site that forgets the argument would
        otherwise silently reintroduce the defect.
        """
        effective = generation if generation is not None else self.producer_generation()
        if effective is not None and effective != self._generation:
            return
        self._failure = _CachedFailure(
            config=config,
            status=status,
            message=message,
            failed_monotonic=time.monotonic(),
        )

    def record_success(
        self,
        config: OpenCodeGoConfig,
        quota: OpenCodeGoQuota,
        *,
        generation: int | None = None,
    ) -> _CachedQuota:
        """Remember a successful read.

        A generation older than the current one means a ``reset()`` happened
        while this fetch was in flight: the entry is still returned to the
        callers who were waiting for it, but it is **not** stored, so the
        invalidated credential's data cannot come back.

        Defaults to the current task's producer generation, so the guard applies
        even when a caller omits the argument.
        """
        entry = _CachedQuota(
            config=config,
            quota=quota,
            checked_at=datetime.now(timezone.utc),
            fetched_monotonic=time.monotonic(),
        )
        effective = generation if generation is not None else self.producer_generation()
        if effective is not None and effective != self._generation:
            return entry
        self._success = entry
        self._failure = None
        return entry

    @property
    def generation(self) -> int:
        """Current cache generation; captured by a producer before it starts."""
        return self._generation

    async def fetch_single_flight(
        self,
        config: OpenCodeGoConfig,
        fetch: Callable[[], Awaitable[_CachedQuota]],
    ) -> _CachedQuota:
        """Run ``fetch`` once for concurrent callers sharing the same config.

        The request runs in a **cache-owned task**, not in the first caller's
        task, and every caller - including the one that started it - waits
        through ``wait_on_shared_future``. This is the difference that matters:
        when the producer ran inline, the first caller being cancelled (a closed
        dashboard tab, a client disconnect) killed the in-flight request and
        cancelled every other waiter with it, even though they were healthy and
        still waiting. Now a cancelled caller detaches in O(1) and the request
        continues serving the others.

        A caller whose config differs starts its own request rather than joining
        - that is what stops a re-keyed subscription from receiving the previous
        key's in-flight answer.
        """
        async with self._lock:
            shared = self._inflight
            if shared is None or shared.done() or self._inflight_config != config:
                shared = asyncio.ensure_future(self._run_producer(fetch, config, self._generation))
                self._inflight = shared
                self._inflight_config = config

        # Never awaited directly: ``wait_on_shared_future`` hands each caller a
        # single-use proxy, so cancelling this await cannot cancel the producer.
        return await wait_on_shared_future(shared)

    async def _run_producer(
        self,
        fetch: Callable[[], Awaitable[_CachedQuota]],
        config: OpenCodeGoConfig,
        generation: int,
    ) -> _CachedQuota:
        """Run the upstream fetch and retire this producer's in-flight slot.

        The slot is cleared on **identity**, so a producer that is finishing can
        never evict a newer one that replaced it after a config change. Clearing
        in ``finally`` also means a failed or cancelled producer cannot wedge
        the cache: the next caller starts a fresh request rather than joining a
        dead future.

        ``generation`` is captured before the fetch starts and exposed through
        ``producer_generation`` so the fetch closure can tag its cache writes.
        A ``reset()`` during the fetch bumps the cache generation, and those
        writes are then discarded rather than resurrecting invalidated state.
        """
        current = asyncio.current_task()
        self._producer_generations[id(current)] = generation
        try:
            return await fetch()
        finally:
            self._producer_generations.pop(id(current), None)
            async with self._lock:
                if self._inflight is current:
                    self._inflight = None
                    self._inflight_config = None

    def producer_generation(self) -> int | None:
        """Generation of the producer running in the current task, if any.

        Lets the fetch closure tag its writes without threading the value
        through every call site.
        """
        return self._producer_generations.get(id(asyncio.current_task()))


_quota_cache = OpenCodeGoQuotaCache()


def get_opencode_go_quota_cache() -> OpenCodeGoQuotaCache:
    return _quota_cache


def reset_opencode_go_quota_cache() -> None:
    """Drop cached quota state, including the credential-derived config key."""
    _quota_cache.reset()


class OpenCodeGoQuotaService:
    """Reads OpenCode Go subscription usage for the dashboard.

    Dependencies are injected so tests exercise the real logic against a fake
    client with no network and no credentials.
    """

    def __init__(
        self,
        settings_repository: SettingsRepository,
        *,
        cache: OpenCodeGoQuotaCache | None = None,
        client_factory: _ClientFactory | None = None,
    ) -> None:
        self._settings_repository = settings_repository
        self._cache = cache if cache is not None else get_opencode_go_quota_cache()
        # Resolved from the module global at construction rather than bound as a
        # default argument, so a test can substitute a fake client without
        # reaching into the service's constructor.
        self._client_factory = client_factory if client_factory is not None else OpenCodeGoClient

    async def get_quota(self) -> OpenCodeGoQuotaResponse:
        settings = await self._settings_repository.get_or_create()
        # Resolved through the backend lane's loader, which is the single
        # audited place the Go credential is decrypted.
        config = quota_config_from_settings(settings)

        if not config.enabled:
            # Gate before any network work: a disabled integration must not poll.
            return _static_response("disabled", "OpenCode Go is disabled")
        if not config.api_key:
            return _static_response(
                "not_configured",
                "OpenCode Go API key is not configured",
            )

        now = time.monotonic()
        fresh = self._cache.fresh(config, now=now)
        if fresh is not None:
            return _quota_response(fresh.quota, checked_at=fresh.checked_at)

        failure = self._cache.recent_failure(config, now=now)
        if failure is not None:
            # Inside the failure TTL, do not re-pay the timeout; still prefer
            # last-good values marked stale over an empty answer.
            return self._degraded_response(config, failure.status, failure.message)

        # Captured before the fetch: these handlers run in the *caller's* task
        # after the producer finished, so they cannot read the producer's
        # generation. A ``reset()`` during the request makes this stale and the
        # failure is then not retained.
        generation = self._cache.generation
        try:
            entry = await self._cache.fetch_single_flight(config, lambda: self._fetch(config))
        except OpenCodeGoError as exc:
            status = _status_for_error(exc)
            # Re-sanitized here even though the client already did it: this is
            # the boundary where upstream text becomes dashboard-visible, and it
            # must hold for any raiser, not only the one client we ship today.
            message = sanitize_opencode_go_message(exc.message, api_key=config.api_key)
            self._cache.record_failure(config, status, message, generation=generation)
            return self._degraded_response(config, status, message)
        except OpenCodeGoQuotaParseError as exc:
            message = sanitize_opencode_go_message(str(exc), api_key=config.api_key)
            self._cache.record_failure(config, "unavailable", message, generation=generation)
            return self._degraded_response(config, "unavailable", message)
        except (asyncio.TimeoutError, OSError) as exc:
            message = sanitize_opencode_go_message(
                f"OpenCode Go usage request failed: {exc.__class__.__name__}",
                api_key=config.api_key,
            )
            self._cache.record_failure(config, "unavailable", message, generation=generation)
            return self._degraded_response(config, "unavailable", message)

        return _quota_response(entry.quota, checked_at=entry.checked_at)

    async def _fetch(self, config: OpenCodeGoConfig) -> _CachedQuota:
        client = self._client_factory(config, header_builder=build_request_headers)
        payload = await client.fetch_usage()
        quota = parse_opencode_go_usage(payload)
        # Tagged with the generation this producer started in: if a settings
        # change reset the cache mid-fetch, the waiting callers still get this
        # answer but it is not retained as invalidated credential-derived state.
        return self._cache.record_success(config, quota, generation=self._cache.producer_generation())

    def _degraded_response(
        self,
        config: OpenCodeGoConfig,
        status: OpenCodeGoQuotaStatus,
        message: str,
    ) -> OpenCodeGoQuotaResponse:
        """Prefer last-good values marked stale; otherwise report the failure.

        Deliberately *not* done for ``unauthorized``: a rejected key means the
        cached numbers may belong to a subscription this key has no relationship
        with, so they are dropped rather than shown as stale.
        """
        if status != "unauthorized":
            cached = self._cache.last_good(config)
            if cached is not None:
                return _quota_response(
                    cached.quota,
                    checked_at=cached.checked_at,
                    status="stale",
                    stale_reason=message,
                )
        if status == "unauthorized":
            self._cache.reset()
        return _static_response(status, message)


def _status_for_error(exc: OpenCodeGoError) -> OpenCodeGoQuotaStatus:
    if isinstance(exc, OpenCodeGoUnavailableError):
        return "unavailable"
    if exc.status_code in (401, 403):
        return "unauthorized"
    if exc.status_code == 429:
        # The usage endpoint itself is throttling us. This is NOT a statement
        # about the subscription's model quota and must not render as exhausted.
        return "rate_limited"
    return "unavailable"


def _static_response(status: OpenCodeGoQuotaStatus, message: str | None) -> OpenCodeGoQuotaResponse:
    """A response with no windows. Empty windows mean unknown, not zero."""
    return OpenCodeGoQuotaResponse(
        status=status,
        scope="unknown",
        message=message,
        checked_at=None,
        refreshed_at=datetime.now(timezone.utc),
        stale=False,
        stale_reason=None,
        model_breakdown_available=False,
        models=[],
        windows=[],
    )


def _quota_response(
    quota: OpenCodeGoQuota,
    *,
    checked_at: datetime,
    status: OpenCodeGoQuotaStatus = "ok",
    stale_reason: str | None = None,
) -> OpenCodeGoQuotaResponse:
    return OpenCodeGoQuotaResponse(
        status=status,
        scope=quota.scope,
        message=None,
        checked_at=checked_at,
        refreshed_at=datetime.now(timezone.utc),
        stale=status == "stale",
        stale_reason=stale_reason,
        model_breakdown_available=quota.model_breakdown_available,
        models=[],
        windows=[
            OpenCodeGoQuotaWindowResponse(
                key=window.key,
                upstream_key=window.upstream_key,
                status=window.status,
                percent_used=window.percent_used,
                resets_at=window.resets_at,
                limit_reached=window.limit_reached,
            )
            for window in quota.windows
        ],
    )
