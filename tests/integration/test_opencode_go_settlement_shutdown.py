"""A settlement in flight when shutdown begins must finish before teardown.

OpenCode Go settles stream accounting on a detached task so a client disconnect
cannot strand the reservation. Those tasks are not owned by ``ProxyService``, so
the existing persistence drain does not cover them: without an explicit join, a
settlement still running when the lifespan closes would be abandoned as the HTTP
client and DB engine shut down - reintroducing the very stranded reservation the
detachment exists to prevent.

These drive the **real** lifespan shutdown against a **real** reserved API-key
reservation settled through ``_settle_stream_terminal_state``, so the assertion
covers actual reservation finalization rather than a synthetic log write.
Synthetic data throughout, no upstream and no credential.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.db.models import ApiKeyUsageReservation, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService, LimitRuleInput
from app.modules.proxy import opencode_go_sidecar_dispatch as dispatch
from app.modules.proxy.claude_sidecar_dispatch import SidecarUsage

pytestmark = pytest.mark.integration


async def _go_logs() -> list[RequestLog]:
    async with SessionLocal() as session:
        rows = list((await session.execute(select(RequestLog))).scalars().all())
    return [row for row in rows if row.source == dispatch.OPENCODE_GO_SIDECAR_SOURCE]


async def _reservation_statuses() -> list[str]:
    async with SessionLocal() as session:
        return list((await session.execute(select(ApiKeyUsageReservation.status))).scalars().all())


async def _reserved_reservation(name: str):
    """Create a key with a real limit and take an actual ``reserved`` reservation.

    A key with no limits produces no reservation row at all, which would make
    any "it was settled" assertion vacuously true - the weakness this file
    exists to avoid.
    """

    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        created = await service.create_key(
            ApiKeyCreateData(
                name=name,
                allowed_models=None,
                limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=50_000)],
            )
        )
        reservation = await service.enforce_limits_for_request(
            created.id,
            request_model="glm-5.3",
            request_service_tier=None,
            request_usage_budget=None,
        )
    assert reservation is not None, "no reservation was created, so this test would be vacuous"
    assert await _reservation_statuses() == ["reserved"]
    return reservation


async def _cancel_remaining_settlements() -> None:
    """Cancel and await any task this test left behind.

    Clearing the strong-reference set alone would abandon a live task to the
    loop's teardown and leak a warning into unrelated tests.
    """

    pending = tuple(dispatch._SETTLEMENT_TASKS)
    for task in pending:
        task.cancel()
    for task in pending:
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    dispatch._SETTLEMENT_TASKS.clear()


@pytest.fixture(autouse=True)
async def _no_leaked_tasks():
    yield
    await _cancel_remaining_settlements()


@pytest.mark.asyncio
async def test_a_pending_reservation_settles_once_during_lifespan_shutdown(_reset_db_state):
    """The gap this closes, against a real reserved reservation.

    The settlement is held mid-flight by an event that is released only from
    inside the shutdown drain itself, so nothing incidental can complete it -
    the drain is the only code path that can, and the ordering is deterministic
    rather than timing-based.
    """

    del _reset_db_state
    from app.main import create_app

    reservation = await _reserved_reservation("shutdown-settlement")

    app = create_app()
    started = asyncio.Event()
    may_finish = asyncio.Event()
    finished = asyncio.Event()

    async def _held_settlement() -> None:
        started.set()
        await may_finish.wait()
        await dispatch._settle_stream_terminal_state(
            api_key=None,
            reservation=reservation,
            model="glm-5.3",
            started_at=0.0,
            usage=SidecarUsage(input_tokens=10, output_tokens=5, cached_input_tokens=0),
            billed_cost_usd=None,
            completed=False,
            error_code="opencode_go_sidecar_stream_interrupted",
            error_message="client disconnected",
        )
        finished.set()

    real_drain = dispatch.drain_opencode_go_settlement_tasks
    drain_calls: list[float] = []

    async def _release_then_drain(*, timeout_seconds: float) -> bool:
        # Release only once the drain is actually running. If the drain were
        # absent this never fires, and the settlement stays blocked forever.
        drain_calls.append(timeout_seconds)
        may_finish.set()
        return await real_drain(timeout_seconds=timeout_seconds)

    import app.main as app_main

    original = app_main._drain_opencode_go_settlements

    async def _patched(timeout_seconds: float) -> None:
        if not await _release_then_drain(timeout_seconds=timeout_seconds):
            raise AssertionError("shutdown drain did not finish the pending settlement")

    app_main._drain_opencode_go_settlements = _patched
    try:
        async with app.router.lifespan_context(app):
            dispatch._settle_detached(_held_settlement())
            await asyncio.wait_for(started.wait(), timeout=5)
            # Still pending inside the lifespan: nothing has settled yet.
            assert await _go_logs() == []
            assert await _reservation_statuses() == ["reserved"]
    finally:
        app_main._drain_opencode_go_settlements = original

    assert drain_calls, "the shutdown path never invoked the OpenCode Go settlement drain"
    assert finished.is_set(), "the held settlement did not run to completion during shutdown"

    # Terminal state reached before teardown, exactly once.
    logs = await _go_logs()
    assert len(logs) == 1, f"expected exactly one request-log row, got {len(logs)}"
    assert logs[0].error_code == "opencode_go_sidecar_stream_interrupted"
    statuses = await _reservation_statuses()
    assert statuses == ["finalized"] or statuses == ["released"], (
        f"reservation was not settled to a terminal state before teardown: {statuses}"
    )
    assert dispatch._SETTLEMENT_TASKS == set()


@pytest.mark.asyncio
async def test_the_drain_runs_before_http_and_db_teardown(_reset_db_state):
    """Ordering: settlement needs the DB, so the drain must precede its close.

    Draining after teardown would be indistinguishable from not draining at all,
    since the settlement's write would fail against a closed engine.
    """

    del _reset_db_state
    import app.main as app_main
    from app.main import create_app

    order: list[str] = []
    original_drain = app_main._drain_opencode_go_settlements
    original_close_http = app_main.close_http_client

    async def _tracked_drain(timeout_seconds: float) -> None:
        order.append("drain_settlements")
        await original_drain(timeout_seconds)

    async def _tracked_close_http() -> None:
        order.append("close_http_client")
        await original_close_http()

    app_main._drain_opencode_go_settlements = _tracked_drain
    app_main.close_http_client = _tracked_close_http
    try:
        app = create_app()
        async with app.router.lifespan_context(app):
            pass
    finally:
        app_main._drain_opencode_go_settlements = original_drain
        app_main.close_http_client = original_close_http

    assert "drain_settlements" in order, "the settlement drain is not part of the shutdown path"
    assert "close_http_client" in order
    assert order.index("drain_settlements") < order.index("close_http_client"), (
        f"settlements were drained after transport teardown: {order}"
    )


@pytest.mark.asyncio
async def test_shutdown_is_not_blocked_by_a_settlement_that_never_finishes(_reset_db_state):
    """A stuck settlement must not hold the process open past its budget.

    Reaching teardown matters more than any single log row: an operator's
    shutdown deadline is a commitment. Asserted with an explicit timeout so a
    regression to an unbounded join fails here rather than hanging the suite.
    """

    del _reset_db_state
    from app.main import create_app

    app = create_app()

    async def _never_finishes() -> None:
        await asyncio.Event().wait()

    async def _run_lifespan() -> None:
        async with app.router.lifespan_context(app):
            dispatch._settle_detached(_never_finishes())
            await asyncio.sleep(0)

    # Generous relative to the drain budget, tight enough that an unbounded
    # join fails instead of hanging.
    await asyncio.wait_for(_run_lifespan(), timeout=90)


@pytest.mark.asyncio
async def test_the_drain_deadline_is_total_not_per_iteration():
    """``timeout_seconds`` bounds the whole drain, across successive waves.

    The discriminating shape is a settlement that *schedules another* as it
    finishes. A per-iteration timer would restart for the new task and keep
    granting a fresh budget wave after wave, overrunning the caller's committed
    shutdown deadline without ever technically timing out. Two equal concurrent
    sleeps would not distinguish the two implementations, since both return at
    the first expiry.
    """

    async def _chain(depth: int) -> None:
        await asyncio.sleep(0.15)
        if depth:
            dispatch._settle_detached(_chain(depth - 1))

    dispatch._settle_detached(_chain(20))

    loop = asyncio.get_running_loop()
    started = loop.time()
    drained = await dispatch.drain_opencode_go_settlement_tasks(timeout_seconds=0.3)
    elapsed = loop.time() - started

    assert drained is False, "a drain that could not finish must report it"
    # 20 waves x 0.15s would be ~3s under a per-iteration timer.
    assert elapsed < 1.0, f"drain overran its total deadline: {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_the_drain_reports_success_when_everything_settles():
    """Control: the failure signal must not be constant."""

    completed = asyncio.Event()

    async def _quick() -> None:
        completed.set()

    dispatch._settle_detached(_quick())

    assert await dispatch.drain_opencode_go_settlement_tasks(timeout_seconds=5) is True
    assert completed.is_set()
    assert dispatch._SETTLEMENT_TASKS == set()
