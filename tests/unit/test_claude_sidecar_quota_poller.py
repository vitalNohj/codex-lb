from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.core.clients.claude_sidecar import (
    ClaudeSidecarClient,
    ClaudeSidecarConfig,
    ClaudeSidecarError,
    ClaudeSidecarUnavailableError,
    SidecarPrefix,
)
from app.modules.claude_sidecar import quota_poller as quota_poller_module
from app.modules.claude_sidecar.quota import (
    SidecarOAuthUsage,
    SidecarOAuthUsageBucket,
    snapshot_from_json,
)
from app.modules.claude_sidecar.quota_poller import ClaudeSidecarQuotaPoller

pytestmark = pytest.mark.unit


@dataclass
class _FakeSettings:
    claude_sidecar_enabled: bool = True
    claude_sidecar_management_key_encrypted: bytes | None = b"enc"
    claude_sidecar_base_url: str = "http://127.0.0.1:8317"
    claude_sidecar_api_key_encrypted: bytes | None = None
    claude_sidecar_model_prefixes_json: str = '["claude"]'
    claude_sidecar_connect_timeout_seconds: float = 8.0
    claude_sidecar_request_timeout_seconds: float = 600.0
    claude_sidecar_models_cache_ttl_seconds: float = 60.0
    claude_sidecar_quota_state_json: str | None = None


@dataclass
class _FakeSettingsCache:
    settings: _FakeSettings | None
    invalidated: int = 0

    async def get(self) -> _FakeSettings:
        assert self.settings is not None
        return self.settings

    async def invalidate(self) -> None:
        self.invalidated += 1


@dataclass
class _FakeRepo:
    last_kwargs: dict[str, Any] = field(default_factory=dict)

    async def update(self, **kwargs: Any) -> None:
        self.last_kwargs.update(kwargs)


@dataclass
class _SessionCtx:
    repo_holder: list[_FakeRepo]

    async def __aenter__(self) -> "_FakeSession":
        session = _FakeSession(repo_holder=self.repo_holder)
        return session

    async def __aexit__(self, *args: Any) -> None:
        return None


@dataclass
class _FakeSession:
    repo_holder: list[_FakeRepo]


def _patch_environment(
    monkeypatch: pytest.MonkeyPatch,
    *,
    settings: _FakeSettings | None,
    client_factory: type[ClaudeSidecarClient] | Any,
    repo_holder: list[_FakeRepo],
) -> _FakeSettingsCache:
    cache = _FakeSettingsCache(settings=settings)
    monkeypatch.setattr(quota_poller_module, "get_settings_cache", lambda: cache)

    def _ctx():
        return _SessionCtx(repo_holder=repo_holder)

    monkeypatch.setattr(quota_poller_module, "get_background_session", _ctx)

    def _build_repo(session: _FakeSession) -> _FakeRepo:
        repo = _FakeRepo()
        repo_holder.append(repo)
        return repo

    monkeypatch.setattr(quota_poller_module, "SettingsRepository", _build_repo)

    class _AlwaysLeader:
        async def try_acquire(self) -> bool:
            return True

    monkeypatch.setattr(quota_poller_module, "_get_leader_election", lambda: _AlwaysLeader())

    def _sidecar_config(_settings: _FakeSettings) -> ClaudeSidecarConfig:
        return ClaudeSidecarConfig(
            enabled=True,
            base_url="http://127.0.0.1:8317",
            api_key=None,
            prefixes=(SidecarPrefix(prefix="claude", strip=False),),
            connect_timeout_seconds=8.0,
            request_timeout_seconds=600.0,
            models_cache_ttl_seconds=60.0,
            management_key="mgmt-key",
        )

    monkeypatch.setattr(quota_poller_module, "sidecar_config_from_settings", _sidecar_config)
    return cache


class _FakeClient:
    def __init__(self, config: ClaudeSidecarConfig) -> None:
        self.config = config

    async def list_auth_files(self) -> list[Mapping[str, Any]]:
        return [
            {
                "provider": "claude",
                "email": "ok@example.com",
                "path": "/tmp/claude-ok@example.com.json",
                "status": "active",
                "quota": {"exceeded": False, "next_recover_at": None},
            }
        ]


class _UnauthorizedClient:
    def __init__(self, config: ClaudeSidecarConfig) -> None:
        self.config = config

    async def list_auth_files(self) -> list[Mapping[str, Any]]:
        raise ClaudeSidecarError(401, "unauthorized")


class _UnreachableClient:
    def __init__(self, config: ClaudeSidecarConfig) -> None:
        self.config = config

    async def list_auth_files(self) -> list[Mapping[str, Any]]:
        raise ClaudeSidecarUnavailableError("connection refused")


class _ErrorClient:
    def __init__(self, config: ClaudeSidecarConfig) -> None:
        self.config = config

    async def list_auth_files(self) -> list[Mapping[str, Any]]:
        raise ClaudeSidecarError(502, "bad gateway")


def _read_snapshot(repo_holder: list[_FakeRepo]):
    assert repo_holder, "expected the poller to write a snapshot"
    repo = repo_holder[-1]
    raw = repo.last_kwargs.get("claude_sidecar_quota_state_json")
    assert isinstance(raw, str), "snapshot json should be a string"
    return snapshot_from_json(raw)


@pytest.mark.asyncio
async def test_poll_once_stores_healthy_snapshot(monkeypatch) -> None:
    repo_holder: list[_FakeRepo] = []
    cache = _patch_environment(
        monkeypatch,
        settings=_FakeSettings(),
        client_factory=_FakeClient,
        repo_holder=repo_holder,
    )
    poller = ClaudeSidecarQuotaPoller(interval_seconds=60.0, enabled=True, _client_factory=_FakeClient)

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert snapshot is not None
    assert snapshot.status == "healthy"
    assert len(snapshot.accounts) == 1
    assert snapshot.accounts[0].email == "ok@example.com"
    assert cache.invalidated == 1


@pytest.mark.asyncio
async def test_poll_once_enriches_oauth_usage_without_storing_token(monkeypatch) -> None:
    repo_holder: list[_FakeRepo] = []
    _patch_environment(
        monkeypatch,
        settings=_FakeSettings(),
        client_factory=_FakeClient,
        repo_holder=repo_holder,
    )

    class _Credential:
        access_token = "sk-ant-oat01-secret"

    async def _load_credential(path: str | None):
        assert path == "/tmp/claude-ok@example.com.json"
        return _Credential()

    async def _fetch_usage(_credential: _Credential) -> SidecarOAuthUsage:
        return SidecarOAuthUsage(
            five_hour=SidecarOAuthUsageBucket(remaining_percent=57.0, resets_at=None),
            seven_day=SidecarOAuthUsageBucket(remaining_percent=82.0, resets_at=None),
        )

    monkeypatch.setattr(quota_poller_module, "load_claude_oauth_credential", _load_credential)
    monkeypatch.setattr(quota_poller_module, "fetch_claude_oauth_usage", _fetch_usage)
    poller = ClaudeSidecarQuotaPoller(interval_seconds=60.0, enabled=True, _client_factory=_FakeClient)

    await poller._poll_once()

    repo = repo_holder[-1]
    raw = repo.last_kwargs["claude_sidecar_quota_state_json"]
    assert "sk-ant-oat01-secret" not in raw
    snapshot = snapshot_from_json(raw)
    assert snapshot is not None
    usage = snapshot.accounts[0].oauth_usage
    assert usage is not None
    assert usage.five_hour is not None
    assert usage.five_hour.remaining_percent == 57.0
    assert usage.seven_day is not None
    assert usage.seven_day.remaining_percent == 82.0


def _snapshot_json_with_usage(five_hour: float, seven_day: float) -> str:
    import json

    return json.dumps(
        {
            "checked_at": "2026-06-11T00:00:00+00:00",
            "status": "healthy",
            "message": None,
            "accounts": [
                {
                    "provider": "claude",
                    "email": "ok@example.com",
                    "path": "/tmp/claude-ok@example.com.json",
                    "status": "active",
                    "quota": {"exceeded": False, "next_recover_at": None},
                    "oauth_usage": {
                        "five_hour": {"remaining_percent": five_hour, "resets_at": None},
                        "seven_day": {"remaining_percent": seven_day, "resets_at": None},
                    },
                }
            ],
        }
    )


@pytest.mark.asyncio
async def test_poll_once_retains_previous_oauth_usage_on_fetch_failure(monkeypatch) -> None:
    repo_holder: list[_FakeRepo] = []
    _patch_environment(
        monkeypatch,
        settings=_FakeSettings(claude_sidecar_quota_state_json=_snapshot_json_with_usage(36.0, 93.0)),
        client_factory=_FakeClient,
        repo_holder=repo_holder,
    )

    class _Credential:
        access_token = "sk-ant-oat01-secret"

    async def _load_credential(path: str | None):
        return _Credential()

    async def _fetch_usage(_credential: _Credential) -> SidecarOAuthUsage:
        from app.modules.claude_sidecar.oauth_usage import ClaudeOAuthUsageError

        raise ClaudeOAuthUsageError("Anthropic OAuth usage endpoint returned HTTP 429")

    monkeypatch.setattr(quota_poller_module, "load_claude_oauth_credential", _load_credential)
    monkeypatch.setattr(quota_poller_module, "fetch_claude_oauth_usage", _fetch_usage)
    poller = ClaudeSidecarQuotaPoller(interval_seconds=60.0, enabled=True, _client_factory=_FakeClient)

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert snapshot is not None
    usage = snapshot.accounts[0].oauth_usage
    assert usage is not None, "fetch failure should carry forward last-known OAuth usage"
    assert usage.five_hour is not None
    assert usage.five_hour.remaining_percent == 36.0
    assert usage.seven_day is not None
    assert usage.seven_day.remaining_percent == 93.0


@pytest.mark.asyncio
async def test_poll_once_replaces_previous_oauth_usage_on_fetch_success(monkeypatch) -> None:
    repo_holder: list[_FakeRepo] = []
    _patch_environment(
        monkeypatch,
        settings=_FakeSettings(claude_sidecar_quota_state_json=_snapshot_json_with_usage(36.0, 93.0)),
        client_factory=_FakeClient,
        repo_holder=repo_holder,
    )

    class _Credential:
        access_token = "sk-ant-oat01-secret"

    async def _load_credential(path: str | None):
        return _Credential()

    async def _fetch_usage(_credential: _Credential) -> SidecarOAuthUsage:
        return SidecarOAuthUsage(
            five_hour=SidecarOAuthUsageBucket(remaining_percent=12.0, resets_at=None),
            seven_day=SidecarOAuthUsageBucket(remaining_percent=88.0, resets_at=None),
        )

    monkeypatch.setattr(quota_poller_module, "load_claude_oauth_credential", _load_credential)
    monkeypatch.setattr(quota_poller_module, "fetch_claude_oauth_usage", _fetch_usage)
    poller = ClaudeSidecarQuotaPoller(interval_seconds=60.0, enabled=True, _client_factory=_FakeClient)

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert snapshot is not None
    usage = snapshot.accounts[0].oauth_usage
    assert usage is not None
    assert usage.five_hour is not None
    assert usage.five_hour.remaining_percent == 12.0


@pytest.mark.asyncio
async def test_poll_once_leaves_oauth_usage_none_without_prior_data(monkeypatch) -> None:
    repo_holder: list[_FakeRepo] = []
    _patch_environment(
        monkeypatch,
        settings=_FakeSettings(claude_sidecar_quota_state_json=None),
        client_factory=_FakeClient,
        repo_holder=repo_holder,
    )

    class _Credential:
        access_token = "sk-ant-oat01-secret"

    async def _load_credential(path: str | None):
        return _Credential()

    async def _fetch_usage(_credential: _Credential) -> SidecarOAuthUsage:
        from app.modules.claude_sidecar.oauth_usage import ClaudeOAuthUsageError

        raise ClaudeOAuthUsageError("Anthropic OAuth usage endpoint returned HTTP 429")

    monkeypatch.setattr(quota_poller_module, "load_claude_oauth_credential", _load_credential)
    monkeypatch.setattr(quota_poller_module, "fetch_claude_oauth_usage", _fetch_usage)
    poller = ClaudeSidecarQuotaPoller(interval_seconds=60.0, enabled=True, _client_factory=_FakeClient)

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert snapshot is not None
    assert snapshot.accounts[0].oauth_usage is None


@pytest.mark.asyncio
async def test_poll_once_no_op_when_sidecar_disabled(monkeypatch) -> None:
    repo_holder: list[_FakeRepo] = []
    _patch_environment(
        monkeypatch,
        settings=_FakeSettings(claude_sidecar_enabled=False),
        client_factory=_FakeClient,
        repo_holder=repo_holder,
    )
    poller = ClaudeSidecarQuotaPoller(interval_seconds=60.0, enabled=True, _client_factory=_FakeClient)

    await poller._poll_once()

    assert repo_holder == []


@pytest.mark.asyncio
async def test_poll_once_no_op_when_management_key_missing(monkeypatch) -> None:
    repo_holder: list[_FakeRepo] = []
    _patch_environment(
        monkeypatch,
        settings=_FakeSettings(claude_sidecar_management_key_encrypted=None),
        client_factory=_FakeClient,
        repo_holder=repo_holder,
    )
    poller = ClaudeSidecarQuotaPoller(interval_seconds=60.0, enabled=True, _client_factory=_FakeClient)

    await poller._poll_once()

    assert repo_holder == []


@pytest.mark.asyncio
async def test_poll_once_classifies_unauthorized(monkeypatch) -> None:
    repo_holder: list[_FakeRepo] = []
    _patch_environment(
        monkeypatch,
        settings=_FakeSettings(),
        client_factory=_UnauthorizedClient,
        repo_holder=repo_holder,
    )
    poller = ClaudeSidecarQuotaPoller(interval_seconds=60.0, enabled=True, _client_factory=_UnauthorizedClient)

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert snapshot is not None
    assert snapshot.status == "unauthorized"
    assert snapshot.accounts == ()


@pytest.mark.asyncio
async def test_poll_once_classifies_unreachable(monkeypatch) -> None:
    repo_holder: list[_FakeRepo] = []
    _patch_environment(
        monkeypatch,
        settings=_FakeSettings(),
        client_factory=_UnreachableClient,
        repo_holder=repo_holder,
    )
    poller = ClaudeSidecarQuotaPoller(interval_seconds=60.0, enabled=True, _client_factory=_UnreachableClient)

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert snapshot is not None
    assert snapshot.status == "unreachable"


@pytest.mark.asyncio
async def test_poll_once_classifies_generic_error(monkeypatch) -> None:
    repo_holder: list[_FakeRepo] = []
    _patch_environment(
        monkeypatch,
        settings=_FakeSettings(),
        client_factory=_ErrorClient,
        repo_holder=repo_holder,
    )
    poller = ClaudeSidecarQuotaPoller(interval_seconds=60.0, enabled=True, _client_factory=_ErrorClient)

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert snapshot is not None
    assert snapshot.status == "error"
    assert snapshot.message == "bad gateway"
