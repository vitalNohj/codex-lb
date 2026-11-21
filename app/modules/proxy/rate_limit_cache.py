from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable

import anyio

from app.core.usage.refresh_policy import USAGE_REFRESH_INTERVAL_SECONDS


class RateLimitHeadersCache:
    def __init__(self) -> None:
        self._entries: OrderedDict[Hashable, tuple[float, dict[str, str]]] = OrderedDict()
        self._lock = anyio.Lock()

    def _get_cached(self, key: Hashable) -> dict[str, str] | None:
        entry = self._entries.get(key)
        if entry is None or time.monotonic() >= entry[0]:
            return None
        self._entries.move_to_end(key)
        return entry[1]

    async def get(
        self,
        compute: Callable[[], Awaitable[dict[str, str]]],
        *,
        key: Hashable = None,
    ) -> dict[str, str]:
        cached = self._get_cached(key)
        if cached is not None:
            return cached

        async with self._lock:
            cached = self._get_cached(key)
            if cached is not None:
                return cached

            headers = await compute()
            # Do not cache a claim of exhaustion. An account can reset, be
            # imported or become eligible before the ordinary summary TTL.
            if not any(name.endswith("-used-percent") and float(value) >= 100 for name, value in headers.items()):
                self._entries[key] = (time.monotonic() + USAGE_REFRESH_INTERVAL_SECONDS, headers)
                self._entries.move_to_end(key)
                if len(self._entries) > 64:
                    self._entries.popitem(last=False)
            return headers

    async def invalidate(self) -> None:
        async with self._lock:
            self._entries.clear()


_rate_limit_headers_cache = RateLimitHeadersCache()


def get_rate_limit_headers_cache() -> RateLimitHeadersCache:
    return _rate_limit_headers_cache
