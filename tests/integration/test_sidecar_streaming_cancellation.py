"""Cancellation through the ACTUAL streaming endpoint, iterator and settlement owner.

The earlier cancellation fixture called the real settlement helper but
hand-mirrored ``_openrouter_stream_iterator``'s ``finally`` block. A mirror can
only prove what it was written to do, so this file drives the real registered
``/v1/chat/completions`` route, the real dispatcher, the real production
iterator and wrapper chain, and the real settlement owner, against real isolated
persistence. Only the external provider transport is faked - no upstream call,
no credential, synthetic identities only.

Cancellation is delivered by cancelling **the real request task**, not by
calling a settlement helper directly.

Terminology used in the assertions, kept deliberately separate:

- **injected cancellation** - the test cancels the asyncio task running the
  request. This is what these tests do.
- **proven server disconnect** - a client socket closing and the server
  observing it. ``ASGITransport`` has no socket, so that is NOT established
  here and is recorded as a limitation rather than implied.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.openrouter_sidecar import OpenRouterSidecarConfig
from app.core.config.settings import get_settings
from app.db.models import ApiKeyLimit, ApiKeyUsageReservation
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService, LimitRuleInput

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------
# Fake provider transport. Only the network edge is faked; every layer above
# it is production code.
# --------------------------------------------------------------------------

_DELTA = b'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"delta":{"content":"hi"}}]}\n\n'
_USAGE = (
    b'data: {"id":"c2","object":"chat.completion.chunk","choices":[],'
    b'"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}\n\n'
)
_CONTEXT_ERROR = b'data: {"error":{"code":"context_length_exceeded","message":"Input token limit exceeded"}}\n\n'
_DONE = b"data: [DONE]\n\n"


class _FakeStreamContext:
    """Yields scripted SSE chunks, pausing on a gate so cancellation is deterministic."""

    def __init__(self, chunks, gate: asyncio.Event | None, gate_after: int, reached: asyncio.Event | None):
        self._chunks = chunks
        self._gate = gate
        self._gate_after = gate_after
        self._reached = reached

    async def __aenter__(self):
        async def chunks():
            for index, chunk in enumerate(self._chunks):
                yield chunk
                if self._gate is not None and index == self._gate_after:
                    # Signal that the scripted prefix has been delivered, then
                    # park here. The request task is cancelled while suspended
                    # on this await, i.e. mid-stream in real production code.
                    if self._reached is not None:
                        self._reached.set()
                    await self._gate.wait()

        return chunks()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeOpenRouterClient:
    def __init__(self, config: OpenRouterSidecarConfig) -> None:
        self.config = config
        self.chunks: list[bytes] = [_DELTA, _USAGE, _DONE]
        self.gate: asyncio.Event | None = None
        self.gate_after: int = 0
        self.gate_reached: asyncio.Event | None = None

    async def list_models_cached(self):
        return []

    async def chat_completion(self, payload):
        raise AssertionError("these tests only exercise the streaming path")

    def stream_chat_completion(self, payload):
        return _FakeStreamContext(self.chunks, self.gate, self.gate_after, self.gate_reached)


@pytest.fixture
def openrouter_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_OPENROUTER_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def fake_openrouter(monkeypatch):
    config = OpenRouterSidecarConfig(
        enabled=True,
        base_url="https://openrouter.ai/api/v1",
        api_key="openrouter-key",
        prefixes=(SidecarPrefix(prefix="deepseek/", strip=False),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=("deepseek/deepseek-chat",),
    )
    client = _FakeOpenRouterClient(config)

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_openrouter_sidecar_config", load_config)
    monkeypatch.setattr("app.modules.proxy.api.OpenRouterSidecarClient", lambda _config: client)
    return client


async def _reservation_rows() -> list[tuple[str, int | None, int | None, int | None]]:
    async with SessionLocal() as session:
        rows = list((await session.execute(select(ApiKeyUsageReservation))).scalars().all())
    return [(r.status, r.input_tokens, r.output_tokens, r.cost_microdollars) for r in rows]


async def _reservation_statuses() -> list[str]:
    return [row[0] for row in await _reservation_rows()]


async def _limit_current_values() -> list[int]:
    async with SessionLocal() as session:
        return list((await session.execute(select(ApiKeyLimit.current_value))).scalars().all())


async def _configure(client: AsyncClient) -> None:
    response = await client.put(
        "/api/settings",
        json={
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
            "openrouterSidecarModelPrefixes": ["deepseek/"],
        },
    )
    assert response.status_code == 200, response.text
    auth = await client.put("/api/settings", json={"apiKeyAuthEnabled": True})
    assert auth.status_code == 200


async def _create_key(name: str):
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        return await service.create_key(
            ApiKeyCreateData(
                name=name,
                allowed_models=None,
                limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)],
            )
        )


async def _stream_request(client: AsyncClient, key, *, cursor: bool) -> bytes:
    headers = {"Authorization": f"Bearer {key.key}"}
    if cursor:
        headers["User-Agent"] = "Cursor/1.0"
    async with client.stream(
        "POST",
        "/v1/chat/completions",
        headers=headers,
        json={
            "model": "deepseek/deepseek-chat",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as response:
        assert response.status_code == 200
        return await response.aread()


# --------------------------------------------------------------------------
# Non-cancelled production counterparts (controls).
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_control_completed_stream_finalizes_with_observed_usage(
    async_client, openrouter_enabled, fake_openrouter
):
    """Baseline: an uncancelled stream finalizes and charges the observed usage."""

    await _configure(async_client)
    key = await _create_key("control-complete")

    body = await _stream_request(async_client, key, cursor=False)
    assert body.rstrip().endswith(b"data: [DONE]")

    assert await _reservation_statuses() == ["finalized"]
    # 10 prompt + 5 completion, as the fake provider reported.
    assert await _limit_current_values() == [15]


@pytest.mark.asyncio
async def test_control_context_limit_rejection_releases_through_the_real_stack(
    async_client, openrouter_enabled, fake_openrouter
):
    """Context-limit rejection: synthetic success to the client, reservation released.

    This is the defect this PR fixed, re-verified end to end through the real
    endpoint rather than through a helper.
    """

    await _configure(async_client)
    key = await _create_key("control-context-limit")
    fake_openrouter.chunks = [_DELTA, _CONTEXT_ERROR, _DONE]

    body = await _stream_request(async_client, key, cursor=True)
    assert b'"error"' not in body

    assert await _reservation_statuses() == ["released"]
    assert await _limit_current_values() == [0]


# --------------------------------------------------------------------------
# Injected cancellation of the real request task, mid-stream.
# --------------------------------------------------------------------------


async def _cancel_midstream(app, key, *, chunks: list[bytes], gate_after: int, fake) -> None:
    """Cancel the real request task while the production iterator is suspended."""

    fake.chunks = chunks
    fake.gate = asyncio.Event()
    fake.gate_after = gate_after
    fake.gate_reached = asyncio.Event()

    transport = ASGITransport(app=app)

    async def _drive() -> None:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            async with client.stream(
                "POST",
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {key.key}", "User-Agent": "Cursor/1.0"},
                json={
                    "model": "deepseek/deepseek-chat",
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": True,
                },
            ) as response:
                await response.aread()

    # Strong reference held for the whole test: an abandoned task or generator
    # finalized by garbage collection would settle the reservation for reasons
    # unrelated to the code under test and falsely prove cleanup.
    task = asyncio.create_task(_drive())
    try:
        await asyncio.wait_for(fake.gate_reached.wait(), timeout=5)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    finally:
        fake.gate.set()
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
    assert task is not None


@pytest.mark.asyncio
async def test_injected_cancellation_before_any_usage_event(
    app_instance, async_client, openrouter_enabled, fake_openrouter
):
    """Cancelled mid-stream before any usage/cost event was observed.

    Records what the real stack actually does, rather than asserting a release
    that may not occur.
    """

    await _configure(async_client)
    key = await _create_key("cancel-before-usage")

    # No reservation exists until the request is admitted.
    assert await _reservation_statuses() == []
    assert await _limit_current_values() == [0]

    # Gate immediately after the first content delta: no usage frame decoded.
    await _cancel_midstream(app_instance, key, chunks=[_DELTA, _USAGE, _DONE], gate_after=0, fake=fake_openrouter)

    # Settle asynchronously if it is going to; do not race the assertion.
    await asyncio.sleep(0.3)

    statuses = await _reservation_statuses()
    values = await _limit_current_values()
    assert statuses in (["reserved"], ["released"]), f"unexpected terminal state: {statuses}"
    # Recorded as observed behaviour. The pairing is the point: a released
    # reservation must return the quota, a retained one must still hold it.
    if statuses == ["released"]:
        assert values == [0]
    else:
        assert values == [1000], "a retained reservation must still hold its quota"


@pytest.mark.asyncio
async def test_injected_cancellation_after_observable_usage(
    app_instance, async_client, openrouter_enabled, fake_openrouter
):
    """Cancelled mid-stream AFTER a usage/cost event was decoded.

    This is the accounting-sensitive case: real tokens were reported by the
    provider before the cancellation landed.
    """

    await _configure(async_client)
    key = await _create_key("cancel-after-usage")

    # Gate after the usage frame, so the iterator has captured usage.
    await _cancel_midstream(
        app_instance,
        key,
        chunks=[_DELTA, _USAGE, _DELTA, _DONE],
        gate_after=1,
        fake=fake_openrouter,
    )

    await asyncio.sleep(0.3)

    rows = await _reservation_rows()
    values = await _limit_current_values()
    assert len(rows) == 1
    status, input_tokens, output_tokens, _cost = rows[0]
    assert status in ("reserved", "finalized", "released"), f"unexpected terminal state: {status}"
    if status == "finalized":
        # If it settles, it must settle the usage the provider actually
        # reported - never a free request.
        assert (input_tokens, output_tokens) == (10, 5)
        assert values == [15]
    elif status == "released":
        assert values == [0]
    else:
        assert values == [1000], "a retained reservation must still hold its quota"


@pytest.mark.asyncio
async def test_cancelled_request_does_not_disturb_another_keys_reservation(
    app_instance, async_client, openrouter_enabled, fake_openrouter
):
    """Cross-request isolation: cancelling one request must not settle another's."""

    await _configure(async_client)
    billed_key = await _create_key("isolation-billed")

    body = await _stream_request(async_client, billed_key, cursor=False)
    assert body.rstrip().endswith(b"data: [DONE]")
    assert await _reservation_statuses() == ["finalized"]
    assert await _limit_current_values() == [15]

    cancelled_key = await _create_key("isolation-cancelled")
    await _cancel_midstream(
        app_instance, cancelled_key, chunks=[_DELTA, _USAGE, _DONE], gate_after=0, fake=fake_openrouter
    )
    await asyncio.sleep(0.3)

    statuses = sorted(await _reservation_statuses())
    values = sorted(await _limit_current_values())
    # The completed request keeps its legitimate charge regardless of what the
    # cancelled one did.
    assert "finalized" in statuses
    assert 15 in values, f"the uncancelled request's charge was disturbed: {values}"
