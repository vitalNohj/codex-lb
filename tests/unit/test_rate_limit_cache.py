from __future__ import annotations

import pytest

import app.modules.proxy.rate_limit_cache as rate_limit_cache_module
from app.modules.proxy.rate_limit_cache import RateLimitHeadersCache

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_cache_hit_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"now": 100.0, "calls": 0}
    monkeypatch.setattr(rate_limit_cache_module.time, "monotonic", lambda: state["now"])

    cache = RateLimitHeadersCache()

    async def compute() -> dict[str, str]:
        state["calls"] += 1
        return {"x-header": f"v{state['calls']}"}

    first = await cache.get(compute)
    second = await cache.get(compute)
    assert first is second
    assert state["calls"] == 1
    assert first == {"x-header": "v1"}


@pytest.mark.asyncio
async def test_cache_recompute_after_ttl_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"now": 100.0, "calls": 0}
    monkeypatch.setattr(rate_limit_cache_module.time, "monotonic", lambda: state["now"])

    cache = RateLimitHeadersCache()

    async def compute() -> dict[str, str]:
        state["calls"] += 1
        return {"x-header": f"v{state['calls']}"}

    first = await cache.get(compute)
    assert state["calls"] == 1

    state["now"] = 161.0  # past 60s TTL
    second = await cache.get(compute)
    assert second is not first
    assert state["calls"] == 2
    assert second == {"x-header": "v2"}


@pytest.mark.asyncio
async def test_cache_keeps_pool_scopes_separate() -> None:
    cache = RateLimitHeadersCache()
    name = "x-codex-primary-used-percent"

    async def model_a() -> dict[str, str]:
        return {name: "25.0"}

    async def model_b() -> dict[str, str]:
        return {name: "75.0"}

    key_a = ("model-a", None, frozenset({"account-a"}))
    key_b = ("model-b", None, frozenset({"account-b"}))
    first = await cache.get(model_a, key=key_a)
    assert await cache.get(model_b, key=key_b) == {name: "75.0"}
    assert await cache.get(model_b, key=key_a) is first


@pytest.mark.asyncio
async def test_cache_recomputes_a_full_window_before_the_next_reply() -> None:
    cache = RateLimitHeadersCache()
    name = "x-codex-primary-used-percent"
    used = 100.0

    async def compute() -> dict[str, str]:
        return {name: str(used)}

    assert await cache.get(compute) == {name: "100.0"}
    used = 50.0
    assert await cache.get(compute) == {name: "50.0"}


@pytest.mark.asyncio
async def test_cache_recompute_after_invalidate(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"now": 100.0, "calls": 0}
    monkeypatch.setattr(rate_limit_cache_module.time, "monotonic", lambda: state["now"])

    cache = RateLimitHeadersCache()

    async def compute() -> dict[str, str]:
        state["calls"] += 1
        return {"x-header": f"v{state['calls']}"}

    first = await cache.get(compute)
    assert state["calls"] == 1

    await cache.invalidate()
    second = await cache.get(compute)
    assert second is not first
    assert state["calls"] == 2
    assert second == {"x-header": "v2"}
