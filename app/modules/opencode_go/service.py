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
from app.modules.opencode_go.config import opencode_go_config_from_settings
from app.modules.opencode_go.schemas import (
    OpenCodeGoQuotaResponse,
    OpenCodeGoQuotaStatus,
    OpenCodeGoQuotaWindowResponse,
)
from app.modules.settings.repository import SettingsRepository

logger = logging.getLogger(__name__)

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
        self._inflight: asyncio.Future[_CachedQuota] | None = None
        self._inflight_config: OpenCodeGoConfig | None = None
        self._lock = asyncio.Lock()

    def reset(self) -> None:
        """Drop all cached state (settings change, test isolation)."""
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

    def record_failure(self, config: OpenCodeGoConfig, status: OpenCodeGoQuotaStatus, message: str) -> None:
        self._failure = _CachedFailure(
            config=config,
            status=status,
            message=message,
            failed_monotonic=time.monotonic(),
        )

    def record_success(self, config: OpenCodeGoConfig, quota: OpenCodeGoQuota) -> _CachedQuota:
        entry = _CachedQuota(
            config=config,
            quota=quota,
            checked_at=datetime.now(timezone.utc),
            fetched_monotonic=time.monotonic(),
        )
        self._success = entry
        self._failure = None
        return entry

    async def fetch_single_flight(
        self,
        config: OpenCodeGoConfig,
        fetch: Callable[[], Awaitable[_CachedQuota]],
    ) -> _CachedQuota:
        """Run ``fetch`` once for concurrent callers sharing the same config.

        The first caller owns the request; the rest attach through
        ``wait_on_shared_future``, so a waiter that times out or is cancelled
        detaches in O(1) and never cancels the shared request the others still
        need. A caller whose config differs starts its own request rather than
        joining - that is what stops a re-keyed subscription from receiving the
        previous key's in-flight answer.
        """
        async with self._lock:
            shared = self._inflight
            if shared is not None and not shared.done() and self._inflight_config == config:
                joined = shared
                owned = None
            else:
                owned = asyncio.get_running_loop().create_future()
                self._inflight = owned
                self._inflight_config = config
                joined = None

        if owned is None:
            assert joined is not None
            return await wait_on_shared_future(joined)

        try:
            entry = await fetch()
        except BaseException as exc:
            owned.set_exception(exc)
            # Consume eagerly: with no waiter attached, the future's destructor
            # would otherwise log "exception was never retrieved".
            owned.exception()
            raise
        else:
            owned.set_result(entry)
            return entry
        finally:
            async with self._lock:
                if self._inflight is owned:
                    self._inflight = None
                    self._inflight_config = None


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
        client_factory: Callable[[OpenCodeGoConfig], OpenCodeGoClient] | None = None,
    ) -> None:
        self._settings_repository = settings_repository
        self._cache = cache if cache is not None else get_opencode_go_quota_cache()
        # Resolved from the module global at construction rather than bound as a
        # default argument, so a test can substitute a fake client without
        # reaching into the service's constructor.
        self._client_factory = client_factory if client_factory is not None else OpenCodeGoClient

    async def get_quota(self) -> OpenCodeGoQuotaResponse:
        settings = await self._settings_repository.get_or_create()
        config = opencode_go_config_from_settings(settings)

        if config is None:
            # The backend integration's settings columns are not present yet.
            return _static_response(
                "not_configured",
                "OpenCode Go is not configured",
            )
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

        try:
            entry = await self._cache.fetch_single_flight(config, lambda: self._fetch(config))
        except OpenCodeGoError as exc:
            status = _status_for_error(exc)
            # Re-sanitized here even though the client already did it: this is
            # the boundary where upstream text becomes dashboard-visible, and it
            # must hold for any raiser, not only the one client we ship today.
            message = sanitize_opencode_go_message(exc.message, api_key=config.api_key)
            self._cache.record_failure(config, status, message)
            return self._degraded_response(config, status, message)
        except OpenCodeGoQuotaParseError as exc:
            message = sanitize_opencode_go_message(str(exc), api_key=config.api_key)
            self._cache.record_failure(config, "unavailable", message)
            return self._degraded_response(config, "unavailable", message)
        except (asyncio.TimeoutError, OSError) as exc:
            message = sanitize_opencode_go_message(
                f"OpenCode Go usage request failed: {exc.__class__.__name__}",
                api_key=config.api_key,
            )
            self._cache.record_failure(config, "unavailable", message)
            return self._degraded_response(config, "unavailable", message)

        return _quota_response(entry.quota, checked_at=entry.checked_at)

    async def _fetch(self, config: OpenCodeGoConfig) -> _CachedQuota:
        client = self._client_factory(config)
        payload = await client.fetch_usage()
        quota = parse_opencode_go_usage(payload)
        return self._cache.record_success(config, quota)

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
