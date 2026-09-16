"""Who settles the reservation on the Cursor context-limit path, and when.

The context-limit rewrite returns early and closes the stream it stops
consuming, so that stream's ``finally`` runs inside the request instead of at
some later event-loop finalization. Review raised a follow-on question that is
**not** the same as the already-proven mid-request cancellation case: does that
in-request close leave settlement exposed to *application shutdown* ordering,
tearing down the database while a settlement is still in flight?

These tests answer it against the real lifespan and a real ``reserved``
reservation, with no upstream, no credential and synthetic data only.

The answer, pinned here rather than asserted in review prose:

1. On the native chat path the close makes the stream's ``finally`` run, and
   that ``finally`` does not itself perform the database write. It hands
   settlement to ``_settle_stream_api_key_usage``, which **detaches** the
   settlement onto a task tracked in ``_background_cleanup_tasks``.
2. Shutdown drains exactly that set via ``drain_persistence_tasks`` **before**
   HTTP/database teardown.

So the close is not the settlement's last chance, and shutdown ordering is
already covered by the existing lifecycle - which is why this change does not
add a second settlement registry. If either property regresses, these fail.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.db.models import ApiKeyLimit, ApiKeyUsageReservation
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService, LimitRuleInput

pytestmark = pytest.mark.integration


async def _reservation_statuses() -> list[str]:
    async with SessionLocal() as session:
        return list((await session.execute(select(ApiKeyUsageReservation.status))).scalars().all())


async def _limit_current_values() -> list[int]:
    async with SessionLocal() as session:
        return list((await session.execute(select(ApiKeyLimit.current_value))).scalars().all())


async def _reserved_reservation(name: str):
    """Create a key with a real limit and take an actual ``reserved`` reservation.

    A key with no applicable limit produces no reservation row at all, which
    would make any "it was settled" assertion vacuously true - precisely the
    weakness that made the original failing test stale.
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
            request_model="deepseek/deepseek-chat",
            request_service_tier=None,
            request_usage_budget=None,
        )
    assert reservation is not None, "no reservation was created, so this test would be vacuous"
    assert await _reservation_statuses() == ["reserved"]
    return reservation


@pytest.mark.asyncio
async def test_a_settlement_still_in_flight_is_drained_before_teardown(_reset_db_state, monkeypatch):
    """A settlement detached by the close must finish before the database closes.

    The settlement is held mid-flight by an event released only from inside the
    shutdown drain itself, so nothing incidental can complete it: the drain is
    the only code path that can, making the ordering deterministic rather than
    timing-based. If the drain did not cover this task, the settlement would
    still be blocked at teardown and the reservation would stay ``reserved``.
    """

    del _reset_db_state
    import app.main as app_main
    from app.main import create_app

    reservation = await _reserved_reservation("cursor-ctx-shutdown")

    app = create_app()
    started = asyncio.Event()
    may_finish = asyncio.Event()
    finished = asyncio.Event()

    async def _held_settlement() -> None:
        started.set()
        await may_finish.wait()
        async with SessionLocal() as session:
            service = ApiKeysService(ApiKeysRepository(session))
            # The context-limit contract: released, never finalized.
            await service.release_usage_reservation(reservation.reservation_id)
        finished.set()

    drain_calls: list[float] = []
    original_drain = app_main._drain_proxy_persistence_tasks
    task: asyncio.Task[None] | None = None

    async def _release_then_drain(
        proxy_service: object,
        timeout_seconds: float,
        *,
        task_name_prefixes: tuple[str, ...] | None = None,
        failure_message: str,
    ) -> bool:
        # Only the *unfiltered* drain covers this task. Shutdown also runs an
        # earlier pre-drain restricted to ``http-bridge-recovery-settlement-``
        # prefixes, which would never await a stream settlement; releasing on
        # that one would let the settlement finish on its own and make this
        # test vacuous - it passed with the real drain deleted until this
        # distinction was added.
        if task_name_prefixes is not None:
            return await original_drain(
                proxy_service,
                timeout_seconds,
                task_name_prefixes=task_name_prefixes,
                failure_message=failure_message,
            )
        # Released only once the covering drain is actually running. Were it
        # absent, this never fires and the settlement stays blocked forever,
        # leaving the reservation ``reserved`` at teardown.
        drain_calls.append(timeout_seconds)
        may_finish.set()
        return await original_drain(proxy_service, timeout_seconds, failure_message=failure_message)

    monkeypatch.setattr(app_main, "_drain_proxy_persistence_tasks", _release_then_drain)
    try:
        async with app.router.lifespan_context(app):
            # One real request so the lazily-built proxy service exists; the
            # shutdown path resolves the same instance.
            from httpx import ASGITransport, AsyncClient

            from app.dependencies import get_proxy_service_for_app

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                await client.get("/health")

            proxy_service = get_proxy_service_for_app(app)
            task = asyncio.create_task(_held_settlement(), name="proxy-stream-api-key-settle-test")
            # Tracked in the same set the shutdown drain awaits, before
            # shutdown starts - as a real in-flight settlement would be.
            proxy_service._background_cleanup_tasks.add(task)
            await asyncio.wait_for(started.wait(), timeout=5)
            # Still pending inside the lifespan: nothing has settled yet.
            assert await _reservation_statuses() == ["reserved"]
    finally:
        if task is not None and not task.done():
            task.cancel()

    assert drain_calls, "the shutdown path never invoked the proxy persistence drain"
    assert finished.is_set(), "the held settlement did not run to completion during shutdown"

    # Terminal state reached before teardown, and the quota actually returned.
    assert await _reservation_statuses() == ["released"]
    assert await _limit_current_values() == [0]


@pytest.mark.asyncio
async def test_the_persistence_drain_runs_before_http_and_database_teardown(_reset_db_state, monkeypatch):
    """Ordering: settlement needs the database, so the drain must precede its close.

    Draining after teardown would be indistinguishable from not draining at
    all, since the settlement's write would fail against a closed engine. This
    is the ordering property the disputed review finding asked about, pinned
    against the real lifespan rather than argued.
    """

    del _reset_db_state
    import app.main as app_main
    from app.main import create_app

    order: list[str] = []
    original_drain = app_main._drain_proxy_persistence_tasks
    original_close_http = app_main.close_http_client

    async def _tracked_drain(
        proxy_service: object,
        timeout_seconds: float,
        *,
        task_name_prefixes: tuple[str, ...] | None = None,
        failure_message: str,
    ) -> bool:
        # Record only the unfiltered drain: the earlier prefix-restricted
        # pre-drain does not cover stream settlements, so counting it would
        # make the ordering assertion pass even with the covering drain gone.
        if task_name_prefixes is None:
            order.append("drain_persistence")
        if task_name_prefixes is not None:
            return await original_drain(
                proxy_service,
                timeout_seconds,
                task_name_prefixes=task_name_prefixes,
                failure_message=failure_message,
            )
        return await original_drain(proxy_service, timeout_seconds, failure_message=failure_message)

    async def _tracked_close_http() -> None:
        order.append("close_http_client")
        await original_close_http()

    monkeypatch.setattr(app_main, "_drain_proxy_persistence_tasks", _tracked_drain)
    monkeypatch.setattr(app_main, "close_http_client", _tracked_close_http)

    app = create_app()
    async with app.router.lifespan_context(app):
        pass

    assert "drain_persistence" in order, "shutdown never drained proxy persistence tasks"
    assert "close_http_client" in order, "shutdown never closed the shared HTTP client"
    assert order.index("drain_persistence") < order.index("close_http_client"), (
        f"persistence drain must precede HTTP/database teardown, got {order}"
    )
