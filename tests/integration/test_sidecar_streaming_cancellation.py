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
from app.db.models import ApiKeyLimit, ApiKeyUsageReservation, RequestLog
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
# Same usage frame, plus a provider-reported billed cost. ``billed_cost_usd``
# survives ``completed=False``, so this drives the settlement helper's
# *finalize* branch rather than its release branch.
_USAGE_WITH_COST = (
    b'data: {"id":"c2","object":"chat.completion.chunk","choices":[],'
    b'"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15,"cost":0.25}}\n\n'
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


async def _sidecar_logs() -> list[tuple[str, str | None]]:
    async with SessionLocal() as session:
        rows = list((await session.execute(select(RequestLog))).scalars().all())
    return [(r.status, r.error_code) for r in rows if r.source == "openrouter_sidecar"]


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


async def _limit_values_by_type() -> dict[str, int]:
    """Durable counters keyed by limit type - the money counter included."""

    async with SessionLocal() as session:
        rows = list((await session.execute(select(ApiKeyLimit))).scalars().all())
    return {row.limit_type.value: row.current_value for row in rows}


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


async def _settle_quiesced(timeout_seconds: float = 5.0) -> None:
    """Wait until no reservation is still ``reserved``, or fail loudly.

    Polls a real condition instead of sleeping a fixed interval: a fixed sleep
    either flakes under load or silently passes by outlasting the very defect
    under test.
    """

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        try:
            # Bound each query by the REMAINING budget, not just the loop
            # condition: a stalled query would otherwise run past the helper's
            # absolute deadline and the caller's timeout would fire instead.
            statuses = await asyncio.wait_for(_reservation_statuses(), timeout=remaining)
        except TimeoutError:
            break
        if statuses and "reserved" not in statuses:
            return
        await asyncio.sleep(min(0.01, max(deadline - loop.time(), 0)))
    # Fall through: the caller's exact assertion reports the real end state.


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
        # Cancel while the production iterator is suspended mid-stream, i.e.
        # during the settlement span rather than between requests.
        for attempt in range(cancel_times):
            task.cancel()
            if attempt + 1 < cancel_times:
                # Re-deliver cancellation while cleanup is in flight.
                await asyncio.sleep(0)
        # Record how the request terminated instead of suppressing everything:
        # accepting any exception (or a normal return) would let a swallowed
        # cancellation pass unnoticed - a defect this PR already had to fix once.
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
    outcome = await _cancel_midstream(
        app_instance, key, chunks=[_DELTA, _USAGE, _DONE], gate_after=0, fake=fake_openrouter
    )
    assert outcome == "CancelledError", f"cancellation did not propagate: {outcome}"

    await _settle_quiesced()

    # EXACT regression. Fails on the pre-fix code, where the cancellation was
    # raised out of ``external_response_settlement``'s price lookup before the
    # settlement helper ran, leaving ``['reserved']`` / ``[1000]``.
    assert await _reservation_rows() == [("released", None, None, None)]
    assert await _limit_current_values() == [0]


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
    outcome = await _cancel_midstream(
        app_instance,
        key,
        chunks=[_DELTA, _USAGE, _DELTA, _DONE],
        gate_after=1,
        fake=fake_openrouter,
    )
    assert outcome == "CancelledError", f"cancellation did not propagate: {outcome}"

    await _settle_quiesced()

    # EXACT regression, pinning the CURRENT contract rather than a preference:
    # ``completed=False`` suppresses settled token usage, and with no
    # billed-cost field no charge resolves, so the existing helper takes its
    # release branch - exactly as an uncancelled interrupted stream does.
    # Fails pre-fix with ``['reserved']`` / ``[1000]``.
    assert await _reservation_rows() == [("released", None, None, None)]
    assert await _limit_current_values() == [0]


@pytest.mark.asyncio
async def test_injected_cancellation_after_provider_billed_cost_finalizes(
    app_instance, async_client, openrouter_enabled, fake_openrouter
):
    """Cancelled after the provider reported a BILLED COST: must finalize, not release.

    ``completed=False`` suppresses settled token usage but NOT ``billed_cost_usd``,
    so a resolved nonzero charge drives the settlement helper's finalize branch.
    This pins that the correction preserves BOTH branches: a blanket release here
    would discard money the provider actually reported.
    """

    await _configure(async_client)
    key = await _create_key("cancel-after-billed-cost", with_cost_limit=True)

    outcome = await _cancel_midstream(
        app_instance,
        key,
        chunks=[_DELTA, _USAGE_WITH_COST, _DELTA, _DONE],
        gate_after=1,
        fake=fake_openrouter,
    )
    await _settle_quiesced()
    assert outcome == "CancelledError", f"cancellation did not propagate: {outcome}"

    rows = await _reservation_rows()
    assert len(rows) == 1
    status, input_tokens, output_tokens, cost_microdollars = rows[0]
    # Finalized, not released - the billed cost survived cancellation.
    assert status == "finalized", f"a provider-billed cancellation must finalize, got {status!r}"
    # $0.25 recorded as microdollars on the reservation row.
    assert cost_microdollars == 250_000, f"wrong durable charge: {cost_microdollars}"
    # Token usage stays suppressed by completed=False; this is the existing
    # contract and the correction does not change it.
    assert (input_tokens, output_tokens) == (0, 0)

    # The reservation row alone does NOT prove the money limit was charged:
    # cost_usd is its own LimitType with its own durable counter. Assert it.
    counters = await _limit_values_by_type()
    assert counters["cost_usd"] == 250_000, f"money limit not charged correctly: {counters}"
    # ...and the token counter is released, because settled token usage is
    # suppressed on an incomplete stream.
    assert counters["total_tokens"] == 0, f"token limit should hold nothing: {counters}"


@pytest.mark.asyncio
async def test_uncancelled_interrupted_stream_matches_the_cancelled_outcome(
    async_client, openrouter_enabled, fake_openrouter
):
    """Equivalence control: cancellation must settle like an ordinary incomplete stream.

    The provider ends the stream without ``[DONE]`` and without a billed cost,
    so this is an incomplete stream that was never cancelled. Its settled state
    is the benchmark the cancelled cases above are held to.
    """

    await _configure(async_client)
    key = await _create_key("uncancelled-incomplete")
    fake_openrouter.chunks = [_DELTA, _USAGE]  # no [DONE]: completed stays False

    await _stream_request(async_client, key, cursor=False)
    await _settle_quiesced()

    assert await _reservation_rows() == [("released", None, None, None)]
    assert await _limit_current_values() == [0]


@pytest.mark.asyncio
async def test_uncancelled_incomplete_billed_stream_charges_the_same_money(
    async_client, openrouter_enabled, fake_openrouter
):
    """Equivalence control for the billed-cost case, without any cancellation.

    An incomplete stream that reported a billed cost is the benchmark the
    cancelled billed-cost case is held to: same finalize branch, same durable
    money counter. If these two ever diverge, cancellation has acquired its own
    accounting behaviour, which is exactly what must not happen.
    """

    await _configure(async_client)
    key = await _create_key("uncancelled-incomplete-billed", with_cost_limit=True)
    fake_openrouter.chunks = [_DELTA, _USAGE_WITH_COST]  # no [DONE]: completed stays False

    await _stream_request(async_client, key, cursor=False)
    await _settle_quiesced()

    rows = await _reservation_rows()
    assert len(rows) == 1
    status, input_tokens, output_tokens, cost_microdollars = rows[0]
    assert status == "finalized"
    assert cost_microdollars == 250_000
    assert (input_tokens, output_tokens) == (0, 0)

    counters = await _limit_values_by_type()
    assert counters["cost_usd"] == 250_000
    assert counters["total_tokens"] == 0


@pytest.mark.asyncio
async def test_settlement_happens_exactly_once_under_repeated_cancellation(
    app_instance, async_client, openrouter_enabled, fake_openrouter
):
    """Repeated cancellation must not double-settle or double-refund."""

    await _configure(async_client)
    key = await _create_key("repeat-cancel")

    outcome = await _cancel_midstream(
        app_instance,
        key,
        chunks=[_DELTA, _USAGE, _DONE],
        gate_after=0,
        fake=fake_openrouter,
        cancel_times=3,
    )
    assert outcome == "CancelledError", f"cancellation did not propagate: {outcome}"
    await _settle_quiesced()

    # Exactly one reservation row, settled once; the quota returns once, never
    # below the pre-request baseline.
    assert await _reservation_rows() == [("released", None, None, None)]
    assert await _limit_current_values() == [0]


async def _cancel_while_suspended_in(
    app,
    key,
    *,
    target_module: str,
    target_name: str,
    monkeypatch,
    chunks: list[bytes],
    fake,
) -> str:
    """Cancel at a deterministic gate immediately BEFORE a real settlement call.

    The chunk gate cancels during provider delivery, which is upstream of the
    work this fix protects. This wraps the genuine callable named by
    ``target_module``/``target_name`` - the price lookup, or the reservation
    write - and parks on a gate placed **immediately before** it, so the
    cancellation is delivered with that call pending and about to run. The real
    implementation then executes unmodified, so persistence is real.

    Stated precisely because the distinction matters: this is a deterministic
    gate in front of the real call, **not** cancellation injected inside an
    already-running database transaction. Cancelling mid-transaction is a
    different scenario and is not covered here.

    Returns how the request task terminated, so the caller can assert that
    cancellation propagated rather than accepting any outcome.
    """

    import importlib

    module = importlib.import_module(target_module)
    real = getattr(module, target_name)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def _suspending(*args, **kwargs):
        entered.set()
        await release.wait()
        return await real(*args, **kwargs)

    monkeypatch.setattr(module, target_name, _suspending)

    fake.chunks = chunks
    fake.gate = None
    fake.gate_reached = None

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

    task = asyncio.create_task(_drive())
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        # Parked at the gate: the real call is pending and about to run.
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        outcome = "completed-normally"
        try:
            await task
        except asyncio.CancelledError:
            outcome = "CancelledError"
        except Exception as exc:  # noqa: BLE001 - reported, never suppressed
            outcome = type(exc).__name__
    finally:
        release.set()
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
    assert task is not None
    return outcome


@pytest.mark.asyncio
async def test_cancellation_during_the_real_price_lookup_still_settles(
    app_instance, async_client, openrouter_enabled, fake_openrouter, monkeypatch
):
    """Cancel at a gate immediately before the real `external_request_cost` lookup.

    This is the exact operation whose CancelledError used to escape before the
    reservation was ever written. The gate sits in front of it; the real lookup
    then runs unmodified and settlement persists for real.
    """

    await _configure(async_client)
    key = await _create_key("cancel-in-price-lookup", with_cost_limit=True)

    outcome = await _cancel_while_suspended_in(
        app_instance,
        key,
        target_module="app.modules.proxy.external_pricing_logging",
        target_name="external_request_cost",
        monkeypatch=monkeypatch,
        chunks=[_DELTA, _USAGE_WITH_COST, _DONE],
        fake=fake_openrouter,
    )
    await _settle_quiesced()

    # Cancellation must actually propagate - not be swallowed into a normal 200.
    assert outcome == "CancelledError", f"cancellation did not propagate: {outcome}"

    rows = await _reservation_rows()
    assert len(rows) == 1
    status, _input_tokens, _output_tokens, cost_microdollars = rows[0]
    assert status == "finalized", f"settlement was lost during the price lookup: {status!r}"
    assert cost_microdollars == 250_000
    assert (await _limit_values_by_type())["cost_usd"] == 250_000


@pytest.mark.asyncio
async def test_cancellation_during_the_real_reservation_write_still_settles(
    app_instance, async_client, openrouter_enabled, fake_openrouter, monkeypatch
):
    """Cancel at a gate immediately before the real reservation write.

    One step later than the price lookup: the durable settlement must still
    complete exactly once, against real persistence. As above this is a gate in
    front of the write, not cancellation inside an open transaction.
    """

    await _configure(async_client)
    key = await _create_key("cancel-in-reservation-write", with_cost_limit=True)

    outcome = await _cancel_while_suspended_in(
        app_instance,
        key,
        target_module="app.modules.proxy.openrouter_sidecar_dispatch",
        target_name="_finalize_or_release_openrouter_reservation",
        monkeypatch=monkeypatch,
        chunks=[_DELTA, _USAGE_WITH_COST, _DONE],
        fake=fake_openrouter,
    )
    await _settle_quiesced()

    assert outcome == "CancelledError", f"cancellation did not propagate: {outcome}"

    rows = await _reservation_rows()
    assert len(rows) == 1
    status, _input_tokens, _output_tokens, cost_microdollars = rows[0]
    assert status == "finalized", f"settlement was lost during the reservation write: {status!r}"
    assert cost_microdollars == 250_000
    assert (await _limit_values_by_type())["cost_usd"] == 250_000
    # Exactly once: the money counter is charged a single time.
    assert len(await _sidecar_logs()) == 1


@pytest.mark.asyncio
async def test_a_settled_charge_is_never_recorded_without_its_request_log(
    app_instance, async_client, openrouter_enabled, fake_openrouter
):
    """A durable charge must not exist with no request-log row explaining it.

    The deferred cancellation is re-raised only after BOTH the settlement and
    the request log are written. Re-raising between them would leave a finalized
    charge and consumed quota that nothing in the log accounts for - an
    unexplainable bill, worse than either outcome alone.
    """

    await _configure(async_client)
    key = await _create_key("charge-needs-its-log")

    await _cancel_midstream(
        app_instance,
        key,
        chunks=[_DELTA, _USAGE_WITH_COST, _DELTA, _DONE],
        gate_after=1,
        fake=fake_openrouter,
    )
    await _settle_quiesced()

    rows = await _reservation_rows()
    assert len(rows) == 1
    status, _input_tokens, _output_tokens, cost_microdollars = rows[0]
    assert status == "finalized"
    assert cost_microdollars == 250_000

    # The charge exists, so its log row must exist too.
    logs = await _sidecar_logs()
    assert len(logs) == 1, f"a finalized charge was recorded with no request log: {logs}"


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
    await _settle_quiesced()

    statuses = sorted(await _reservation_statuses())
    values = sorted(await _limit_current_values())
    # The completed request keeps its legitimate charge regardless of what the
    # cancelled one did.
    assert "finalized" in statuses
    assert 15 in values, f"the uncancelled request's charge was disturbed: {values}"
