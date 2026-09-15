"""Regression coverage for the discovery runner's settings-object lifetime.

The existing API test suite monkeypatches ``provider_access`` on BOTH the
service and the runner module, so the real function - the one that reads the
``DashboardSettings`` ORM row - never executes under test. That is precisely
why a runner that crashed on every tick could ship: the boundary that failed in
production was patched away.

These tests therefore drive the REAL ``provider_access`` against the REAL
session lifecycle and stub only the outbound HTTP transport, which is the one
thing a test must never reach. No provider connectivity, no credentials beyond
a synthetic fixture value, no live database.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.crypto import TokenEncryptor
from app.core.utils.time import utcnow
from app.db.models import DashboardSettings, FreeModelDiscoveryRun, FreeModelDiscoveryRunItem
from app.db.session import SessionLocal
from app.modules.free_model_discovery import runner as runner_module
from app.modules.free_model_discovery.repository import FreeModelDiscoveryRepository
from app.modules.free_model_discovery.runner import FreeModelDiscoveryRunner
from app.modules.free_model_discovery.service import FreeModelDiscoveryService

pytestmark = pytest.mark.integration

# Synthetic, never a real credential. Shaped like a provider key so the
# redaction contract is exercised honestly.
_FAKE_OPENROUTER_KEY = "sk-test-openrouter-0123456789"


class _FakeResponse:
    def __init__(self, status: int, text: str) -> None:
        self.status = status
        self._text = text

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def text(self) -> str:
        return self._text


class _FakeHttpSession:
    """Stands in for the leased aiohttp session inside the sidecar client.

    Everything below ``provider_access`` stays real - config building, key
    decryption, client construction, header assembly, response parsing - and
    only the socket is replaced, so the probe path under test is the shipped
    one.
    """

    def __init__(self, post_bodies: Mapping[str, list[str]]) -> None:
        self._post_bodies = {model_id: list(bodies) for model_id, bodies in post_bodies.items()}
        self.posted_models: list[str] = []
        self.authorization_headers: list[str | None] = []

    def post(self, url: str, *, headers, json, timeout) -> _FakeResponse:
        del url, timeout
        model_id = str(json["model"])
        self.posted_models.append(model_id)
        self.authorization_headers.append(headers.get("Authorization"))
        bodies = self._post_bodies.get(model_id)
        if not bodies:
            raise AssertionError(f"unexpected probe for {model_id}")
        return _FakeResponse(200, bodies.pop(0))


class _FakeLease:
    def __init__(self, session: _FakeHttpSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeHttpSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def _ok_body() -> str:
    return json.dumps({"choices": [{"message": {"role": "assistant", "content": "ok"}}]})


class _FailingRunner(FreeModelDiscoveryRunner):
    """Runner whose driver dies of an unexpected internal error.

    A subclass rather than a monkeypatched attribute because the runner is a
    slotted dataclass, and because overriding the driver keeps the error
    HANDLING path - the code actually under test - entirely real.
    """

    error: BaseException = RuntimeError("settings went away")

    async def drive_run(self, run_id: str) -> None:
        del run_id
        raise self.error


class _CancelledRunner(FreeModelDiscoveryRunner):
    async def drive_run(self, run_id: str) -> None:
        del run_id
        raise asyncio.CancelledError


@pytest.fixture
def fake_transport(monkeypatch) -> _FakeHttpSession:
    """Replace only the outbound socket; the sidecar client itself stays real."""

    http_session = _FakeHttpSession({"vendor/model-a:free": [_ok_body()]})
    monkeypatch.setattr(
        "app.core.clients.openrouter_sidecar.lease_http_session",
        lambda: _FakeLease(http_session),
    )
    # Keep the test fast without changing any behaviour under test.
    monkeypatch.setattr(runner_module, "_WAIT_SLICE_SECONDS", 0.01)
    return http_session


async def _enable_openrouter_sidecar() -> None:
    """Configure OpenRouter exactly as an operator would, through the real row."""

    async with SessionLocal() as session:
        settings = (await session.execute(select(DashboardSettings))).scalar_one()
        settings.openrouter_sidecar_enabled = True
        settings.openrouter_sidecar_api_key_encrypted = TokenEncryptor().encrypt(_FAKE_OPENROUTER_KEY)
        settings.orcarouter_sidecar_enabled = False
        settings.orcarouter_sidecar_api_key_encrypted = None
        await session.commit()


async def _create_run(model_ids: list[str]) -> str:
    now = utcnow()
    async with SessionLocal() as session:
        run = await FreeModelDiscoveryRepository(session).create_run(
            started_at=now,
            deadline_at=now + timedelta(hours=1),
            pacing_floor_seconds=0.01,
            pacing_cap_seconds=0.05,
            max_attempts_per_item=3,
            items=[("openrouter", model_id, "new") for model_id in model_ids],
        )
        return run.id


@pytest.mark.asyncio
async def test_runner_probes_through_the_real_provider_access(async_client, fake_transport):
    """The defect reproduction: a run must actually reach its first probe.

    ``drive_run`` used to load ``DashboardSettings`` inside a background-session
    block and then call ``provider_access`` AFTER that block closed, so the
    first attribute read raised ``DetachedInstanceError`` - before any provider
    client was built. Against the unfixed runner this test fails with zero
    probes issued and the run still ``running``.
    """

    del async_client  # the app fixture supplies the migrated schema and settings row
    await _enable_openrouter_sidecar()
    run_id = await _create_run(["vendor/model-a:free"])

    await FreeModelDiscoveryRunner(enabled=True).drive_run(run_id)

    # A probe was actually issued, through the real client the real
    # provider_access built from the real settings row.
    assert fake_transport.posted_models == ["vendor/model-a:free"]
    assert fake_transport.authorization_headers == [f"Bearer {_FAKE_OPENROUTER_KEY}"]

    async with SessionLocal() as session:
        run = await session.get(FreeModelDiscoveryRun, run_id)
        assert run is not None
        assert run.status == "completed"
        assert run.error_message is None
        items = (await session.execute(select(FreeModelDiscoveryRunItem))).scalars().all()
        assert [(item.model_id, item.state, item.attempts) for item in items] == [("vendor/model-a:free", "passed", 1)]


@pytest.mark.asyncio
async def test_run_progress_is_visible_to_the_operator_after_a_real_probe(async_client, fake_transport):
    """What the operator sees: the run API reports a finished, resolved run.

    The captain's symptom was a run stuck on ``Running`` forever, so the
    user-visible surface - not just the row - is asserted here.
    """

    await _enable_openrouter_sidecar()
    run_id = await _create_run(["vendor/model-a:free"])

    await FreeModelDiscoveryRunner(enabled=True).drive_run(run_id)

    body = (await async_client.get(f"/api/free-model-discovery/runs/{run_id}")).json()
    assert body["status"] == "completed"
    assert body["errorMessage"] is None
    assert body["finishedAt"] is not None
    assert body["counts"]["passed"] == 1
    assert body["counts"]["queued"] == 0


@pytest.mark.asyncio
async def test_unexpected_driver_error_marks_the_run_failed_instead_of_running(async_client):
    """A dead run must never keep rendering as ``Running``.

    The broad ``except Exception`` in ``_drive_as_leader`` only logged, so the
    crash above left the row ``running`` with ``error_message`` NULL - which is
    also what blocked every later run under the single-active index. Any
    unexpected internal failure must now become a truthful terminal result.
    """

    await _enable_openrouter_sidecar()
    run_id = await _create_run(["vendor/model-a:free"])

    await _FailingRunner(enabled=True)._drive_as_leader()

    async with SessionLocal() as session:
        run = await session.get(FreeModelDiscoveryRun, run_id)
        assert run is not None
        assert run.status == "failed"
        assert run.finished_at is not None
        assert run.error_message is not None
        assert "RuntimeError" in run.error_message
        # Queued work is resolved, not left dangling behind a terminal run.
        items = (await session.execute(select(FreeModelDiscoveryRunItem))).scalars().all()
        assert [item.state for item in items] == ["unresolved"]

    body = (await async_client.get(f"/api/free-model-discovery/runs/{run_id}")).json()
    assert body["status"] == "failed"
    assert "RuntimeError" in body["errorMessage"]

    # A failed run releases the single-active index, so discovery is not wedged.
    async with SessionLocal() as session:
        assert await FreeModelDiscoveryRepository(session).get_active_run() is None


@pytest.mark.asyncio
async def test_failure_text_never_leaks_a_provider_credential(async_client):
    """``error_message`` is served to the dashboard, so it gets the same
    credential-aware redaction the probe outcomes already get."""

    del async_client
    await _enable_openrouter_sidecar()
    run_id = await _create_run(["vendor/model-a:free"])

    runner = _FailingRunner(enabled=True)
    runner.error = RuntimeError(f"upstream echoed Authorization: Bearer {_FAKE_OPENROUTER_KEY}")

    await runner._drive_as_leader()

    async with SessionLocal() as session:
        run = await session.get(FreeModelDiscoveryRun, run_id)
        assert run is not None
        assert run.error_message is not None
        assert _FAKE_OPENROUTER_KEY not in run.error_message
        assert "[redacted]" in run.error_message


@pytest.mark.asyncio
async def test_cancelled_driver_leaves_the_run_running_for_the_next_boot(async_client):
    """Cancellation is shutdown, not failure.

    ``_finalize`` deliberately leaves a run ``running`` when ``_stop`` is set so
    the next boot resumes it; the new failure path must preserve that rather
    than converting every restart into a ``failed`` run.
    """

    del async_client
    await _enable_openrouter_sidecar()
    run_id = await _create_run(["vendor/model-a:free"])

    with pytest.raises(asyncio.CancelledError):
        await _CancelledRunner(enabled=True)._drive_as_leader()

    async with SessionLocal() as session:
        run = await session.get(FreeModelDiscoveryRun, run_id)
        assert run is not None
        assert run.status == "running"
        assert run.error_message is None


@pytest.mark.asyncio
async def test_failure_never_overwrites_an_already_terminal_run(async_client):
    """The failure write is guarded on the run still being ``running``.

    A cancel or deadline finalize that lands first owns the terminal state; a
    late error from the same (or another replica's) driver must not rewrite a
    truthful ``cancelled``/``completed`` into ``failed``.
    """

    del async_client
    await _enable_openrouter_sidecar()
    run_id = await _create_run(["vendor/model-a:free"])

    now = utcnow()
    async with SessionLocal() as session:
        await FreeModelDiscoveryRepository(session).finish_run(run_id, status="cancelled", finished_at=now)

    await FreeModelDiscoveryRunner(enabled=True)._fail_run(run_id, RuntimeError("late error"))

    async with SessionLocal() as session:
        run = await session.get(FreeModelDiscoveryRun, run_id)
        assert run is not None
        assert run.status == "cancelled"
        assert run.error_message is None


@pytest.mark.asyncio
async def test_disabled_provider_is_still_resolved_from_live_settings(async_client, fake_transport):
    """The unusable-provider branch must also read settings while they are live.

    It is reached through the same resolution, so a regression there would be
    just as invisible: the run would crash rather than park the provider.
    """

    del async_client
    async with SessionLocal() as session:
        settings = (await session.execute(select(DashboardSettings))).scalar_one()
        settings.openrouter_sidecar_enabled = False
        settings.openrouter_sidecar_api_key_encrypted = None
        await session.commit()

    run_id = await _create_run(["vendor/model-a:free"])

    await FreeModelDiscoveryRunner(enabled=True).drive_run(run_id)

    assert fake_transport.posted_models == []
    async with SessionLocal() as session:
        run = await session.get(FreeModelDiscoveryRun, run_id)
        assert run is not None
        assert run.status == "completed"
        items = (await session.execute(select(FreeModelDiscoveryRunItem))).scalars().all()
        assert [item.state for item in items] == ["unresolved"]
        assert items[0].last_outcome is not None
        assert "disabled" in items[0].last_outcome


@pytest.mark.asyncio
async def test_real_provider_access_pins_the_passed_model(async_client, fake_transport):
    """End to end through the real boundary: a pass lands in the pin list.

    Ties the restored probe path to the operator-visible outcome discovery
    exists for, so a future regression cannot be green while the feature does
    nothing.
    """

    await _enable_openrouter_sidecar()
    run_id = await _create_run(["vendor/model-a:free"])

    await FreeModelDiscoveryRunner(enabled=True).drive_run(run_id)

    settings_body = (await async_client.get("/api/settings")).json()
    assert settings_body["openrouterSidecarFullModels"] == ["vendor/model-a:free"]

    async with SessionLocal() as session:
        items = (await session.execute(select(FreeModelDiscoveryRunItem))).scalars().all()
        assert items[0].added_to_full_models is True
        # The pin went through the real service against the real settings row.
        assert await FreeModelDiscoveryService(session)._repository.get_run(run_id) is not None
