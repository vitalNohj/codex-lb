"""Cancellation through the real OpenAI-compat streaming stack.

The generic OpenAI-compat streaming iterator was added as a clone of
the OpenRouter sidecar *before* PR 58 corrected that sidecar's settlement, so
it shipped the defect PR 58 fixed: cost resolution, reservation settlement and
request logging awaited directly in the generator's ``finally``. A client
disconnect cancels the request task, the first ``await`` in that ``finally``
re-raises the pending ``CancelledError``, and the reservation stays ``reserved``
with the caller's quota consumed until stale reclamation.

Reported on https://github.com/vitalNohj/codex-lb/pull/59 and reproduced here
before fixing. Structure and terminology deliberately mirror
``tests/integration/test_sidecar_streaming_cancellation.py`` (PR 58's harness):
the real registered ``/v1/chat/completions`` route, the real dispatcher, the real
production iterator, and the real settlement owner, against real isolated
persistence. Only the external provider transport is faked - no upstream call,
no credential.

Cancellation is delivered by cancelling **the real request task**, not by calling
a settlement helper directly. As in PR 58's file, that is an *injected
cancellation*, not a *proven server disconnect*: ``ASGITransport`` has no socket.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.openai_compat_sidecar import OpenAICompatSidecarConfig
from app.db.models import ApiKeyLimit, ApiKeyUsageReservation, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService, LimitRuleInput

pytestmark = pytest.mark.integration

ENDPOINT_ID = "2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a"
OPENAI_COMPAT_SOURCE = f"openai_compat:{ENDPOINT_ID}"
MODEL = "z-ai/glm-5.3"

_DELTA = b'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"delta":{"content":"hi"}}]}\n\n'
_USAGE = (
    b'data: {"id":"c2","object":"chat.completion.chunk","choices":[],'
    b'"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}\n\n'
)
# Same usage frame plus an echoed ``cost`` field. Neither of these two providers
# is in ``PER_REQUEST_BILLED_PROVIDERS`` - the OpenSpec change explicitly refuses
# to treat an OpenAI-compat cost echo as billed spend - so this pins that
# the cancellation fix did not quietly start charging it.
_USAGE_WITH_COST = (
    b'data: {"id":"c2","object":"chat.completion.chunk","choices":[],'
    b'"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15,"cost":0.25}}\n\n'
)
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


class _FakeSidecarClient:
    def __init__(self, config) -> None:
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
def fake_openai_compat(monkeypatch):
    config = OpenAICompatSidecarConfig(
        endpoint_id=ENDPOINT_ID,
        name="Vast",
        enabled=True,
        base_url="https://openai.vast.ai/demo/v1",
        api_key="compat-key",
        prefixes=(SidecarPrefix(prefix="vast/", strip=True),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=(MODEL,),
    )
    client = _FakeSidecarClient(config)

    async def load_configs():
        return (config,)

    async def load_claude_disabled():
        return None

    monkeypatch.setattr("app.modules.proxy.api.load_openai_compat_configs", load_configs)
    monkeypatch.setattr("app.modules.proxy.api.OpenAICompatSidecarClient", lambda _config: client)
    monkeypatch.setattr("app.modules.proxy.api.get_openai_compat_sidecar_client", lambda _config: client)
    monkeypatch.setattr("app.modules.proxy.api.load_sidecar_config", load_claude_disabled)
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


async def _limit_values_by_type() -> dict[str, int]:
    """Durable counters keyed by limit type - the money counter included."""

    async with SessionLocal() as session:
        rows = list((await session.execute(select(ApiKeyLimit))).scalars().all())
    return {row.limit_type.value: row.current_value for row in rows}


async def _sidecar_logs(source: str) -> list[tuple[str, str | None]]:
    async with SessionLocal() as session:
        rows = list((await session.execute(select(RequestLog))).scalars().all())
    return [(r.status, r.error_code) for r in rows if r.source == source]


async def _configure_openai_compat(client: AsyncClient) -> None:
    auth = await client.put("/api/settings", json={"apiKeyAuthEnabled": True})
    assert auth.status_code == 200


async def _create_key(name: str, *, with_cost_limit: bool = False):
    """Create a key with a token limit, and optionally a separate money limit.

    ``cost_usd`` is its own ``LimitType`` with its own durable counter, so a
    reservation's ``cost_microdollars`` does NOT by itself prove the money limit
    was charged. Tests that care about money must assert that counter.
    """

    limits = [LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)]
    if with_cost_limit:
        # 1 USD expressed in microdollars, the unit the counter accrues in.
        limits.append(LimitRuleInput(limit_type="cost_usd", limit_window="weekly", max_value=1_000_000))
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        return await service.create_key(ApiKeyCreateData(name=name, allowed_models=None, limits=limits))


async def _settle_quiesced(timeout_seconds: float = 5.0) -> None:
    """Wait until no reservation is still ``reserved``, or fall through.

    Polls a real condition instead of sleeping a fixed interval: a fixed sleep
    either flakes under load or silently passes by outlasting the very defect
    under test. Falling through lets the caller's exact assertion report the
    real end state.
    """

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return
        try:
            statuses = await asyncio.wait_for(_reservation_statuses(), timeout=remaining)
        except TimeoutError:
            return
        if statuses and "reserved" not in statuses:
            return
        await asyncio.sleep(min(0.01, max(deadline - loop.time(), 0)))


async def _cancel_midstream(app, key, *, chunks: list[bytes], gate_after: int, fake, cancel_times: int = 1) -> str:
    """Cancel the real request task while the production iterator is suspended.

    Returns how the request task terminated so callers can assert that the
    cancellation actually propagated.
    """

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
                headers={"Authorization": f"Bearer {key.key}"},
                json={
                    "model": MODEL,
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
        # Cancel while the production iterator is suspended mid-stream, i.e.
        # during the settlement span rather than between requests.
        for attempt in range(cancel_times):
            task.cancel()
            if attempt + 1 < cancel_times:
                # Re-deliver cancellation while cleanup is in flight.
                await asyncio.sleep(0)
        # Record how the request terminated instead of suppressing everything:
        # accepting any exception (or a normal return) would let a swallowed
        # cancellation pass unnoticed.
        outcome = "completed-normally"
        try:
            await task
        except asyncio.CancelledError:
            outcome = "CancelledError"
        except Exception as exc:  # noqa: BLE001 - reported to the caller, never hidden
            outcome = type(exc).__name__
    finally:
        fake.gate.set()
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
    assert task is not None
    return outcome


# --------------------------------------------------------------------------
# Generic OpenAI-compatible endpoints
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_compat_control_completed_stream_finalizes_with_observed_usage(async_client, fake_openai_compat):
    """Baseline: an uncancelled stream finalizes and charges the observed usage."""

    await _configure_openai_compat(async_client)
    key = await _create_key("compat-control-complete")

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": MODEL, "messages": [{"role": "user", "content": "hi"}], "stream": True},
    ) as response:
        assert response.status_code == 200
        body = await response.aread()
    assert body.rstrip().endswith(b"data: [DONE]")

    assert await _reservation_statuses() == ["finalized"]
    assert await _limit_current_values() == [15]
    assert await _sidecar_logs(OPENAI_COMPAT_SOURCE) == [("success", None)]


@pytest.mark.asyncio
async def test_openai_compat_injected_cancellation_before_any_usage_event(
    app_instance, async_client, fake_openai_compat
):
    """Cancelled mid-stream before any usage/cost event was observed.

    EXACT regression: fails pre-fix with ``['reserved']`` / ``[1000]``.
    """

    await _configure_openai_compat(async_client)
    key = await _create_key("compat-cancel-before-usage")

    assert await _reservation_statuses() == []
    assert await _limit_current_values() == [0]

    outcome = await _cancel_midstream(
        app_instance, key, chunks=[_DELTA, _USAGE, _DONE], gate_after=0, fake=fake_openai_compat
    )
    assert outcome == "CancelledError", f"cancellation did not propagate: {outcome}"

    await _settle_quiesced()

    assert await _reservation_rows() == [("released", None, None, None)]
    assert await _limit_current_values() == [0]


@pytest.mark.asyncio
async def test_openai_compat_injected_cancellation_after_observable_usage(
    app_instance, async_client, fake_openai_compat
):
    """Cancelled mid-stream AFTER a usage event was decoded."""

    await _configure_openai_compat(async_client)
    key = await _create_key("compat-cancel-after-usage")

    outcome = await _cancel_midstream(
        app_instance, key, chunks=[_DELTA, _USAGE, _DELTA, _DONE], gate_after=1, fake=fake_openai_compat
    )
    assert outcome == "CancelledError", f"cancellation did not propagate: {outcome}"

    await _settle_quiesced()

    assert await _reservation_rows() == [("released", None, None, None)]
    assert await _limit_current_values() == [0]


@pytest.mark.asyncio
async def test_openai_compat_cancellation_does_not_charge_an_echoed_cost_as_billed_spend(
    app_instance, async_client, fake_openai_compat
):
    """An echoed ``cost`` is not billed spend for a generic endpoint, cancelled or not.

    Arbitrary OpenAI-compatible servers are not in
    ``PER_REQUEST_BILLED_PROVIDERS``: an unknown server's ``cost`` field means
    nothing verifiable, so it must not become a durable charge.
    """

    await _configure_openai_compat(async_client)
    key = await _create_key("compat-cancel-echoed-cost", with_cost_limit=True)

    outcome = await _cancel_midstream(
        app_instance,
        key,
        chunks=[_DELTA, _USAGE_WITH_COST, _DELTA, _DONE],
        gate_after=1,
        fake=fake_openai_compat,
    )
    await _settle_quiesced()
    assert outcome == "CancelledError", f"cancellation did not propagate: {outcome}"

    rows = await _reservation_rows()
    assert len(rows) == 1
    status, _input_tokens, _output_tokens, cost_microdollars = rows[0]
    assert status == "released", f"an echoed cost must not finalize a charge, got {status!r}"
    assert cost_microdollars in (None, 0)
    assert (await _limit_values_by_type())["cost_usd"] == 0


@pytest.mark.asyncio
async def test_openai_compat_a_settled_reservation_is_never_recorded_without_its_request_log(
    app_instance, async_client, fake_openai_compat
):
    """Settlement and its request log are one deferred unit."""

    await _configure_openai_compat(async_client)
    key = await _create_key("compat-settle-needs-log", with_cost_limit=True)

    await _cancel_midstream(
        app_instance,
        key,
        chunks=[_DELTA, _USAGE_WITH_COST, _DELTA, _DONE],
        gate_after=1,
        fake=fake_openai_compat,
    )
    await _settle_quiesced()

    assert await _reservation_statuses() == ["released"]
    assert len(await _sidecar_logs(OPENAI_COMPAT_SOURCE)) == 1


@pytest.mark.asyncio
async def test_openai_compat_settlement_happens_exactly_once_under_repeated_cancellation(
    app_instance, async_client, fake_openai_compat
):
    """Re-delivered cancellation must not double-settle."""

    await _configure_openai_compat(async_client)
    key = await _create_key("compat-cancel-twice")

    await _cancel_midstream(
        app_instance,
        key,
        chunks=[_DELTA, _USAGE, _DELTA, _DONE],
        gate_after=1,
        fake=fake_openai_compat,
        cancel_times=3,
    )
    await _settle_quiesced()

    assert await _reservation_statuses() == ["released"]
    assert await _limit_current_values() == [0]
    assert len(await _sidecar_logs(OPENAI_COMPAT_SOURCE)) == 1
