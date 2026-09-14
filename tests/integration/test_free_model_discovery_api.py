from __future__ import annotations

import json
from collections import deque
from collections.abc import Mapping
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.clients.claude_sidecar import SidecarModel
from app.core.clients.openrouter_sidecar import OpenRouterSidecarError, OpenRouterSidecarUnavailableError
from app.core.clients.orcarouter_sidecar import reset_orcarouter_sidecar_client_cache
from app.core.utils.time import utcnow
from app.db.models import DashboardSettings, FreeModelDiscoveryRun, FreeModelProbeState
from app.db.session import SessionLocal
from app.modules.free_model_discovery import runner as runner_module
from app.modules.free_model_discovery import service as service_module
from app.modules.free_model_discovery.runner import FreeModelDiscoveryRunner
from app.modules.free_model_discovery.service import ProviderAccess

pytestmark = pytest.mark.integration


class _FakeClient:
    """Scripted sidecar: ``responses[model_id]`` is a queue of bodies or exceptions."""

    def __init__(self, models: list[SidecarModel], responses: Mapping[str, list[object]]) -> None:
        self.models = models
        self.responses = {model_id: deque(items) for model_id, items in responses.items()}
        self.calls: list[str] = []

    async def list_models(self) -> list[SidecarModel]:
        return list(self.models)

    async def chat_completion(self, payload):
        model_id = str(payload["model"])
        self.calls.append(model_id)
        queue = self.responses.get(model_id)
        if not queue:
            raise AssertionError(f"unexpected probe for {model_id}")
        outcome = queue.popleft()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _ok() -> dict[str, object]:
    return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}


def _empty() -> dict[str, object]:
    return {"choices": [{"message": {"role": "assistant", "content": ""}}]}


@pytest.fixture(autouse=True)
def _clear_client_caches():
    reset_orcarouter_sidecar_client_cache()
    yield
    reset_orcarouter_sidecar_client_cache()


@pytest.fixture
def fake_clients(monkeypatch):
    """Route both providers to scripted clients. OrcaRouter is disabled so the
    plan exercises the unusable-provider branch alongside the live one."""

    openrouter = _FakeClient(
        models=[
            SidecarModel(id="deepseek/deepseek-r1:free", owned_by="deepseek"),
            SidecarModel(id="qwen/qwen3-coder:free", owned_by="qwen"),
            SidecarModel(id="meta/llama-4:free", owned_by="meta"),
            SidecarModel(id="openrouter/free"),
            SidecarModel(id="z-ai/glm-5.3-flash"),
            SidecarModel(id="already/pinned:free"),
        ],
        responses={
            "deepseek/deepseek-r1:free": [_ok()],
            "qwen/qwen3-coder:free": [_empty()],
            "meta/llama-4:free": [
                OpenRouterSidecarError(429, "slow down", body={"error": {"message": "slow down"}}),
                OpenRouterSidecarUnavailableError("reset"),
                _ok(),
            ],
        },
    )

    def _access(settings, provider):
        if provider == "openrouter":
            return ProviderAccess("ok", None, openrouter)
        return ProviderAccess("disabled", "OrcaRouter sidecar is disabled", None)

    monkeypatch.setattr(service_module, "provider_access", _access)
    monkeypatch.setattr(runner_module, "provider_access", _access)
    # Keep the test fast: near-zero pacing, retries are immediately due.
    monkeypatch.setattr(service_module, "DEFAULT_PACING_FLOOR_SECONDS", 0.01)
    monkeypatch.setattr(service_module, "DEFAULT_PACING_CAP_SECONDS", 0.05)
    monkeypatch.setattr(runner_module, "_INCONCLUSIVE_REQUEUE", timedelta(seconds=0))
    monkeypatch.setattr(runner_module, "_WAIT_SLICE_SECONDS", 0.01)
    return openrouter


async def _seed_pinned(model_ids: list[str]) -> None:
    async with SessionLocal() as session:
        settings = (await session.execute(select(DashboardSettings))).scalar_one()
        settings.openrouter_sidecar_full_models_json = json.dumps(model_ids)
        await session.commit()


async def _drive(run_id: str) -> None:
    runner = FreeModelDiscoveryRunner(enabled=True)
    await runner.drive_run(run_id)


@pytest.mark.asyncio
async def test_plan_groups_candidates_and_reports_provider_state(async_client, fake_clients):
    await _seed_pinned(["already/pinned:free"])

    response = await async_client.get("/api/free-model-discovery/plan")
    assert response.status_code == 200
    body = response.json()
    assert body["activeRunId"] is None
    by_provider = {plan["provider"]: plan for plan in body["providers"]}

    openrouter = by_provider["openrouter"]
    assert openrouter["status"] == "ok"
    assert openrouter["discoveredCount"] == 6
    assert openrouter["freeCount"] == 5
    assert openrouter["alreadyPinnedCount"] == 1
    assert openrouter["skippedSelectorCount"] == 1
    assert [(c["modelId"], c["group"]) for c in openrouter["candidates"]] == [
        ("deepseek/deepseek-r1:free", "new"),
        ("meta/llama-4:free", "new"),
        ("qwen/qwen3-coder:free", "new"),
    ]
    assert openrouter["candidates"][0]["ownedBy"] == "deepseek"

    orcarouter = by_provider["orcarouter"]
    assert orcarouter["status"] == "disabled"
    assert orcarouter["candidates"] == []


@pytest.mark.asyncio
async def test_run_lifecycle_pins_passed_models_and_records_cooldown(async_client, fake_clients):
    await _seed_pinned(["already/pinned:free"])

    response = await async_client.post(
        "/api/free-model-discovery/runs",
        json={
            "selections": [
                {"provider": "openrouter", "modelId": "deepseek/deepseek-r1:free"},
                {"provider": "openrouter", "modelId": "qwen/qwen3-coder:free"},
                {"provider": "openrouter", "modelId": "META/llama-4:free"},
            ]
        },
    )
    assert response.status_code == 201, response.text
    run = response.json()
    run_id = run["id"]
    assert run["status"] == "running"
    assert run["counts"] == {"total": 3, "queued": 3, "passed": 0, "failed": 0, "unresolved": 0, "added": 0}

    # A second start while one is active is a conflict.
    response = await async_client.post(
        "/api/free-model-discovery/runs",
        json={"selections": [{"provider": "openrouter", "modelId": "deepseek/deepseek-r1:free"}]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "discovery_run_active"

    plan = (await async_client.get("/api/free-model-discovery/plan")).json()
    assert plan["activeRunId"] == run_id

    await _drive(run_id)

    response = await async_client.get(f"/api/free-model-discovery/runs/{run_id}")
    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "completed"
    assert run["finishedAt"] is not None
    assert run["counts"] == {"total": 3, "queued": 0, "passed": 2, "failed": 1, "unresolved": 0, "added": 2}
    items = {item["modelId"]: item for item in run["items"]}

    passed = items["deepseek/deepseek-r1:free"]
    assert passed["state"] == "passed"
    assert passed["attempts"] == 1
    assert passed["lastHttpStatus"] == 200
    assert passed["contentOkMatch"] is True
    assert passed["addedToFullModels"] is True

    failed = items["qwen/qwen3-coder:free"]
    assert failed["state"] == "failed"
    assert failed["contentChars"] == 0
    assert failed["addedToFullModels"] is False

    retried = items["meta/llama-4:free"]
    assert retried["state"] == "passed"
    assert retried["attempts"] == 3
    assert retried["addedToFullModels"] is True

    # 429 and transport failures never count as verdicts.
    assert fake_clients.calls.count("meta/llama-4:free") == 3

    # Pinned list grew, preserving the operator's existing entries.
    settings = (await async_client.get("/api/settings")).json()
    assert settings["openrouterSidecarFullModels"] == [
        "already/pinned:free",
        "deepseek/deepseek-r1:free",
        "meta/llama-4:free",
    ]

    # Cross-run memory: the failure is in cooldown, the passes are clean.
    async with SessionLocal() as session:
        states = {row.model_id: row for row in (await session.execute(select(FreeModelProbeState))).scalars().all()}
    assert states["qwen/qwen3-coder:free"].failure_streak == 1
    assert states["qwen/qwen3-coder:free"].cooldown_until is not None
    assert states["qwen/qwen3-coder:free"].cooldown_until > utcnow() + timedelta(minutes=50)
    assert states["deepseek/deepseek-r1:free"].failure_streak == 0
    assert states["deepseek/deepseek-r1:free"].cooldown_until is None

    # The next plan excludes the newly pinned ids and puts the failure in cooldown.
    plan = (await async_client.get("/api/free-model-discovery/plan")).json()
    assert plan["activeRunId"] is None
    openrouter = next(p for p in plan["providers"] if p["provider"] == "openrouter")
    assert openrouter["alreadyPinnedCount"] == 3
    assert [(c["modelId"], c["group"]) for c in openrouter["candidates"]] == [("qwen/qwen3-coder:free", "cooldown")]
    assert openrouter["candidates"][0]["failureStreak"] == 1

    runs = (await async_client.get("/api/free-model-discovery/runs")).json()
    assert runs["activeRunId"] is None
    assert [r["id"] for r in runs["runs"]] == [run_id]
    assert runs["runs"][0]["counts"]["passed"] == 2

    current = (await async_client.get("/api/free-model-discovery/runs/current")).json()
    assert current["id"] == run_id


@pytest.mark.asyncio
async def test_start_rejects_stale_selection(async_client, fake_clients):
    response = await async_client.post(
        "/api/free-model-discovery/runs",
        json={"selections": [{"provider": "openrouter", "modelId": "z-ai/glm-5.3-flash"}]},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "discovery_selection_stale"

    response = await async_client.post(
        "/api/free-model-discovery/runs",
        json={"selections": [{"provider": "openrouter", "modelId": "openrouter/free"}]},
    )
    assert response.status_code == 400

    response = await async_client.post(
        "/api/free-model-discovery/runs",
        json={
            "selections": [
                {"provider": "openrouter", "modelId": "deepseek/deepseek-r1:free"},
                {"provider": "openrouter", "modelId": "DEEPSEEK/deepseek-r1:free"},
            ]
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_cancel_marks_queued_items_unresolved_and_next_plan_reports_them(async_client, fake_clients):
    await _seed_pinned(["already/pinned:free"])
    response = await async_client.post(
        "/api/free-model-discovery/runs",
        json={
            "selections": [
                {"provider": "openrouter", "modelId": "deepseek/deepseek-r1:free"},
                {"provider": "openrouter", "modelId": "qwen/qwen3-coder:free"},
            ]
        },
    )
    run_id = response.json()["id"]

    response = await async_client.post(f"/api/free-model-discovery/runs/{run_id}/cancel")
    assert response.status_code == 200
    assert response.json()["cancelRequested"] is True
    assert response.json()["status"] == "running"

    await _drive(run_id)

    run = (await async_client.get(f"/api/free-model-discovery/runs/{run_id}")).json()
    assert run["status"] == "cancelled"
    assert run["counts"]["unresolved"] == 2
    assert fake_clients.calls == []

    response = await async_client.post(f"/api/free-model-discovery/runs/{run_id}/cancel")
    assert response.status_code == 409

    plan = (await async_client.get("/api/free-model-discovery/plan")).json()
    openrouter = next(p for p in plan["providers"] if p["provider"] == "openrouter")
    groups = {c["modelId"]: c["group"] for c in openrouter["candidates"]}
    assert groups == {
        "deepseek/deepseek-r1:free": "unresolved",
        "qwen/qwen3-coder:free": "unresolved",
        "meta/llama-4:free": "new",
    }


@pytest.mark.asyncio
async def test_expired_deadline_finishes_run_as_expired(async_client, fake_clients):
    response = await async_client.post(
        "/api/free-model-discovery/runs",
        json={"selections": [{"provider": "openrouter", "modelId": "deepseek/deepseek-r1:free"}]},
    )
    run_id = response.json()["id"]
    async with SessionLocal() as session:
        run = await session.get(FreeModelDiscoveryRun, run_id)
        assert run is not None
        run.deadline_at = utcnow() - timedelta(seconds=1)
        await session.commit()

    await _drive(run_id)

    run_body = (await async_client.get(f"/api/free-model-discovery/runs/{run_id}")).json()
    assert run_body["status"] == "expired"
    assert run_body["counts"]["unresolved"] == 1
    assert fake_clients.calls == []


@pytest.mark.asyncio
async def test_unknown_run_is_404(async_client):
    response = await async_client.get("/api/free-model-discovery/runs/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "discovery_run_not_found"
    response = await async_client.get("/api/free-model-discovery/runs/current")
    assert response.status_code == 200
    assert response.json() is None


@pytest.mark.asyncio
async def test_second_concurrent_run_insert_is_rejected_by_the_database(async_client):
    """The single-active guard must not depend on the service's pre-check.

    ``start_run`` checks for an active run, then rebuilds the plan - which calls
    the provider APIs - before inserting. Two rapid clicks can both pass that
    check inside the network window, so the database has to be the arbiter.
    This drives the repository directly to reproduce exactly that interleaving.
    """

    from app.modules.free_model_discovery.repository import (
        ActiveRunExistsError,
        FreeModelDiscoveryRepository,
    )

    now = utcnow()
    common = {
        "started_at": now,
        "deadline_at": now + timedelta(hours=1),
        "pacing_floor_seconds": 1.0,
        "pacing_cap_seconds": 2.0,
        "max_attempts_per_item": 1,
    }

    async with SessionLocal() as session:
        first = await FreeModelDiscoveryRepository(session).create_run(
            items=[("openrouter", "a/b:free", "new")], **common
        )
        assert first.status == "running"

    # A second insert, as a racing request would attempt after its own plan
    # rebuild, is refused rather than creating a parallel sweep.
    async with SessionLocal() as session:
        with pytest.raises(ActiveRunExistsError):
            await FreeModelDiscoveryRepository(session).create_run(
                items=[("openrouter", "c/d:free", "new")], **common
            )

    # Exactly one run is live, and the session survived the rejection.
    async with SessionLocal() as session:
        running = (
            (
                await session.execute(
                    select(FreeModelDiscoveryRun).where(FreeModelDiscoveryRun.status == "running")
                )
            )
            .scalars()
            .all()
        )
        assert len(running) == 1
        assert running[0].id == first.id
