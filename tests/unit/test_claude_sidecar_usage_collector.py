from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.core.clients.claude_sidecar import ClaudeSidecarConfig, ClaudeSidecarError
from app.modules.claude_sidecar import usage_collector as usage_collector_module
from app.modules.claude_sidecar.usage_collector import ClaudeSidecarUsageCollector
from app.modules.claude_sidecar.usage_queue import ClaudeSidecarUsageRecord

pytestmark = pytest.mark.unit


@dataclass
class _FakeSettings:
    claude_sidecar_enabled: bool = True
    claude_sidecar_management_key_encrypted: bytes | None = b"enc"
    claude_sidecar_usage_collection_enabled: bool = True
    claude_sidecar_usage_queue_batch_size: int = 2


@dataclass
class _FakeSettingsCache:
    settings: _FakeSettings

    async def get(self) -> _FakeSettings:
        return self.settings


@dataclass
class _FakeRepo:
    inserted: list[ClaudeSidecarUsageRecord] = field(default_factory=list)

    async def insert_usage_events(self, records: list[ClaudeSidecarUsageRecord]) -> int:
        self.inserted.extend(records)
        return len(records)


@dataclass
class _SessionCtx:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *args: Any) -> None:
        return None


class _FakeClient:
    batches: list[list[dict[str, Any]]] = []
    calls = 0

    def __init__(self, config: ClaudeSidecarConfig) -> None:
        self.config = config

    async def pop_usage_queue(self, _count: int) -> list[dict[str, Any]]:
        batch = type(self).batches[type(self).calls] if type(self).calls < len(type(self).batches) else []
        type(self).calls += 1
        return batch


class _UnauthorizedClient:
    def __init__(self, config: ClaudeSidecarConfig) -> None:
        self.config = config

    async def pop_usage_queue(self, _count: int) -> list[dict[str, Any]]:
        raise ClaudeSidecarError(401, "unauthorized")


def _patch_environment(
    monkeypatch: pytest.MonkeyPatch,
    *,
    settings: _FakeSettings,
    repo: _FakeRepo,
) -> None:
    monkeypatch.setattr(usage_collector_module, "get_settings_cache", lambda: _FakeSettingsCache(settings))
    monkeypatch.setattr(usage_collector_module, "get_background_session", lambda: _SessionCtx())
    monkeypatch.setattr(usage_collector_module, "ClaudeSidecarUsageRepository", lambda _session: repo)

    class _AlwaysLeader:
        async def try_acquire(self) -> bool:
            return True

    monkeypatch.setattr(usage_collector_module, "_get_leader_election", lambda: _AlwaysLeader())

    def _sidecar_config(_settings: _FakeSettings) -> ClaudeSidecarConfig:
        return ClaudeSidecarConfig(
            enabled=True,
            base_url="http://127.0.0.1:8317",
            api_key=None,
            model_prefixes=("claude",),
            connect_timeout_seconds=8.0,
            request_timeout_seconds=600.0,
            models_cache_ttl_seconds=60.0,
            management_key="mgmt-key",
        )

    monkeypatch.setattr(usage_collector_module, "sidecar_config_from_settings", _sidecar_config)


def _raw_record(request_id: str) -> dict[str, Any]:
    return {
        "timestamp": "2026-05-05T12:00:00Z",
        "request_id": request_id,
        "tokens": {"total_tokens": 10},
    }


@pytest.mark.asyncio
async def test_collect_once_no_op_when_gated_off(monkeypatch) -> None:
    repo = _FakeRepo()
    _patch_environment(
        monkeypatch,
        settings=_FakeSettings(claude_sidecar_management_key_encrypted=None),
        repo=repo,
    )
    _FakeClient.calls = 0
    _FakeClient.batches = [[_raw_record("req_1")]]
    collector = ClaudeSidecarUsageCollector(
        interval_seconds=15,
        enabled=True,
        batch_size=2,
        _client_factory=_FakeClient,
    )

    await collector._collect_once()

    assert _FakeClient.calls == 0
    assert repo.inserted == []


@pytest.mark.asyncio
async def test_collect_once_drains_until_short_batch(monkeypatch) -> None:
    repo = _FakeRepo()
    _patch_environment(monkeypatch, settings=_FakeSettings(), repo=repo)
    _FakeClient.calls = 0
    _FakeClient.batches = [
        [_raw_record("req_1"), _raw_record("req_2")],
        [_raw_record("req_3")],
    ]
    collector = ClaudeSidecarUsageCollector(
        interval_seconds=15,
        enabled=True,
        batch_size=2,
        _client_factory=_FakeClient,
    )

    await collector._collect_once()

    assert _FakeClient.calls == 2
    assert [record.request_id for record in repo.inserted] == ["req_1", "req_2", "req_3"]


@pytest.mark.asyncio
async def test_collect_once_stops_after_bounded_batches(monkeypatch) -> None:
    repo = _FakeRepo()
    _patch_environment(monkeypatch, settings=_FakeSettings(), repo=repo)
    _FakeClient.calls = 0
    _FakeClient.batches = [[_raw_record(f"req_{idx}"), _raw_record(f"req_{idx}_b")] for idx in range(5)]
    collector = ClaudeSidecarUsageCollector(
        interval_seconds=15,
        enabled=True,
        batch_size=2,
        max_batches_per_tick=3,
        _client_factory=_FakeClient,
    )

    await collector._collect_once()

    assert _FakeClient.calls == 3
    assert len(repo.inserted) == 6


@pytest.mark.asyncio
async def test_collect_once_swallows_unauthorized(monkeypatch) -> None:
    repo = _FakeRepo()
    _patch_environment(monkeypatch, settings=_FakeSettings(), repo=repo)
    collector = ClaudeSidecarUsageCollector(
        interval_seconds=15,
        enabled=True,
        batch_size=2,
        _client_factory=_UnauthorizedClient,
    )

    await collector._collect_once()

    assert repo.inserted == []
