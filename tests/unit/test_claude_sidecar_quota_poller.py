from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, Mock

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
    GrokCreditsQuota,
    GrokCreditWindow,
    SidecarAuthQuota,
    SidecarOAuthUsage,
    SidecarOAuthUsageBucket,
    SidecarQuotaSnapshot,
    SidecarRateLimitHold,
    snapshot_from_json,
    snapshot_to_json,
)
from app.modules.claude_sidecar.quota_poller import ClaudeSidecarQuotaPoller
from app.modules.settings.repository import SettingsRepository
from tests.unit.test_grok_credits import _grpc_text, _message, _weekly_config

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_poll_preserves_exclusions_saved_during_oauth_read(monkeypatch, tmp_path):
    from app.modules.claude_sidecar.service import ClaudeSidecarService

    path = tmp_path / "claude-test.json"
    path.write_text(json.dumps({"excluded_models": []}))
    monkeypatch.setattr("app.modules.claude_sidecar.excluded_models.default_auth_dir", lambda: tmp_path)
    entered = asyncio.Event()
    resume = asyncio.Event()
    settings = _FakeSettings()
    repos = []

    class Client(ClaudeSidecarClient):
        api_call = _FakeClient.api_call

        async def list_auth_files(self):
            return [{"name": path.name, "provider": "claude", "path": str(path)}]

    cache = _patch_environment(monkeypatch, settings=settings, client_factory=Client, repo_holder=repos)
    monkeypatch.setattr("app.modules.claude_sidecar.service.get_settings_cache", lambda: cache)

    async def attach(client, parsed, previous):
        assert parsed[0].excluded_models == ()
        settings.claude_sidecar_quota_state_json = snapshot_to_json(
            quota_poller_module.SidecarQuotaSnapshot(
                checked_at=quota_poller_module.datetime.now(quota_poller_module.timezone.utc),
                status="healthy",
                message=None,
                accounts=tuple(parsed),
            )
        )
        entered.set()
        await resume.wait()
        return parsed

    monkeypatch.setattr(quota_poller_module, "_attach_oauth_usage", attach)
    poller = ClaudeSidecarQuotaPoller(interval_seconds=60, enabled=True, _client_factory=Client)
    task = asyncio.create_task(poller._poll_locked())
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        path.write_text(json.dumps({"excluded_models": ["claude-fable-*"]}))

        async def update_operational(**kwargs):
            settings.claude_sidecar_quota_state_json = kwargs["claude_sidecar_quota_state_json"]

        save_repo = Mock(spec=SettingsRepository)
        save_repo.get_fresh = AsyncMock(return_value=settings)
        save_repo.update_operational = AsyncMock(side_effect=update_operational)
        await ClaudeSidecarService(save_repo)._patch_snapshot_excluded_models(path.name, ["claude-fable-*"])
        saved = snapshot_from_json(settings.claude_sidecar_quota_state_json)
        assert saved is not None
        assert saved.accounts[0].excluded_models == ("claude-fable-*",)
    finally:
        resume.set()
        await task
    published = snapshot_from_json(repos[-1].last_kwargs["claude_sidecar_quota_state_json"])
    assert published is not None
    assert published.accounts[0].excluded_models == ("claude-fable-*",)
    assert published.accounts[0].excluded_models_available is True


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
    settings: _FakeSettings | None = None

    async def get_fresh(self) -> _FakeSettings:
        if self.settings is None:
            raise RuntimeError("Claude sidecar quota poll has no settings row")
        return self.settings

    async def update(self, **kwargs: Any) -> None:
        self.last_kwargs.update(kwargs)

    async def update_operational(self, **kwargs: Any) -> None:
        self.last_kwargs.update(kwargs)
        raw = kwargs.get("claude_sidecar_quota_state_json")
        if self.settings is not None and isinstance(raw, str):
            self.settings.claude_sidecar_quota_state_json = raw


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
        repo = _FakeRepo(settings=settings)
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
                "auth_index": "0",
                "status": "active",
                "quota": {"exceeded": False, "next_recover_at": None},
            }
        ]

    async def api_call(
        self,
        *,
        auth_index: str,
        method: str,
        url: str,
        header: Mapping[str, str],
    ) -> Any:
        return {
            "five_hour": {"utilization": 25.0, "resets_at": None},
            "seven_day": {"utilization": 50.0, "resets_at": None},
        }


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

    async def _fetch_usage(client: Any, auth_index: str) -> SidecarOAuthUsage:
        assert auth_index == "0"
        return SidecarOAuthUsage(
            five_hour=SidecarOAuthUsageBucket(remaining_percent=57.0, resets_at=None),
            seven_day=SidecarOAuthUsageBucket(remaining_percent=82.0, resets_at=None),
        )

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
                    "auth_index": "0",
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

    async def _fetch_usage(client: Any, auth_index: str) -> SidecarOAuthUsage:
        from app.modules.claude_sidecar.oauth_usage import ClaudeOAuthUsageError

        raise ClaudeOAuthUsageError("Anthropic OAuth usage endpoint returned HTTP 429")

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

    async def _fetch_usage(client: Any, auth_index: str) -> SidecarOAuthUsage:
        return SidecarOAuthUsage(
            five_hour=SidecarOAuthUsageBucket(remaining_percent=12.0, resets_at=None),
            seven_day=SidecarOAuthUsageBucket(remaining_percent=88.0, resets_at=None),
        )

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

    async def _fetch_usage(client: Any, auth_index: str) -> SidecarOAuthUsage:
        from app.modules.claude_sidecar.oauth_usage import ClaudeOAuthUsageError

        raise ClaudeOAuthUsageError("Anthropic OAuth usage endpoint returned HTTP 429")

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


_AUTH_NAME = "claude-a@example.com.json"
_FUTURE = datetime(2099, 1, 1, tzinfo=timezone.utc)
_LATER = datetime(2099, 6, 1, tzinfo=timezone.utc)


def _usage(
    five_hour: float,
    seven_day: float,
    *,
    five_reset: datetime | None,
    seven_reset: datetime | None = None,
) -> SidecarOAuthUsage:
    return SidecarOAuthUsage(
        five_hour=SidecarOAuthUsageBucket(remaining_percent=five_hour, resets_at=five_reset),
        seven_day=SidecarOAuthUsageBucket(remaining_percent=seven_day, resets_at=seven_reset),
    )


def _hold_snapshot_json(*holds: SidecarRateLimitHold, disabled: bool = True) -> str:
    account = SidecarAuthQuota(
        name=_AUTH_NAME,
        auth_index="1",
        email="a@example.com",
        status="active",
        status_message=None,
        disabled=disabled,
        unavailable=False,
        quota_exceeded=False,
        next_recover_at=None,
        model_states=(),
        success=0,
        failed=0,
        last_refresh=None,
    )
    snapshot = SidecarQuotaSnapshot(
        checked_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
        status="healthy",
        message=None,
        accounts=(account,),
        rate_limit_holds=holds,
    )
    return snapshot_to_json(snapshot)


class _MutableAuthClient:
    def __init__(self) -> None:
        self.disabled = False
        self.fail_disable = False
        self.fail_enable = False
        self.fail_after_lists: int | None = None
        self.list_calls = 0
        self.patches: list[tuple[str, bool]] = []
        self.extra_files: list[Mapping[str, Any]] = []

    async def list_auth_files(self) -> list[Mapping[str, Any]]:
        self.list_calls += 1
        if self.fail_after_lists is not None and self.list_calls > self.fail_after_lists:
            raise ClaudeSidecarError(503, "list failed")
        return [
            {
                "name": _AUTH_NAME,
                "provider": "claude",
                "email": "a@example.com",
                "auth_index": "1",
                "disabled": self.disabled,
                "status": "error",
                "status_message": "rate_limit_error",
            },
            *self.extra_files,
        ]

    async def patch_auth_file_disabled(self, name: str, disabled: bool) -> None:
        if disabled and self.fail_disable:
            raise ClaudeSidecarError(503, "disable failed")
        if not disabled and self.fail_enable:
            raise ClaudeSidecarError(503, "enable failed")
        self.patches.append((name, disabled))
        self.disabled = disabled


def _poll_with_usage(
    monkeypatch: pytest.MonkeyPatch,
    settings: _FakeSettings,
    client: _MutableAuthClient,
    usage: SidecarOAuthUsage,
):
    repo_holder: list[_FakeRepo] = []

    def _factory(_config: ClaudeSidecarConfig) -> _MutableAuthClient:
        return client

    _patch_environment(monkeypatch, settings=settings, client_factory=_factory, repo_holder=repo_holder)

    async def _fetch(_client: Any, auth_index: str) -> SidecarOAuthUsage:
        assert auth_index == "1"
        return usage

    monkeypatch.setattr(quota_poller_module, "fetch_claude_oauth_usage", _fetch)
    poller = ClaudeSidecarQuotaPoller(interval_seconds=60.0, enabled=True, _client_factory=_factory)
    return repo_holder, poller


@pytest.mark.asyncio
async def test_poll_disables_auth_until_five_hour_reset(monkeypatch) -> None:
    client = _MutableAuthClient()
    repo_holder, poller = _poll_with_usage(
        monkeypatch,
        _FakeSettings(),
        client,
        _usage(0.0, 70.0, five_reset=_FUTURE),
    )

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert client.patches == [(_AUTH_NAME, True)]
    assert snapshot is not None
    assert snapshot.accounts[0].disabled is True
    assert snapshot.rate_limit_holds == (SidecarRateLimitHold(name=_AUTH_NAME, until=_FUTURE, released=False),)


@pytest.mark.asyncio
async def test_poll_enables_auth_when_owned_hold_expires(monkeypatch) -> None:
    client = _MutableAuthClient()
    client.disabled = True
    settings = _FakeSettings(
        claude_sidecar_quota_state_json=_hold_snapshot_json(
            SidecarRateLimitHold(name=_AUTH_NAME, until=_FUTURE, released=False)
        )
    )
    repo_holder, poller = _poll_with_usage(
        monkeypatch,
        settings,
        client,
        _usage(40.0, 70.0, five_reset=_FUTURE),
    )

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert client.patches == [(_AUTH_NAME, False)]
    assert snapshot is not None
    assert snapshot.accounts[0].disabled is False
    assert snapshot.rate_limit_holds == ()


@pytest.mark.asyncio
async def test_poll_leaves_operator_pause_disabled(monkeypatch) -> None:
    client = _MutableAuthClient()
    client.disabled = True
    repo_holder, poller = _poll_with_usage(
        monkeypatch,
        _FakeSettings(),
        client,
        _usage(0.0, 0.0, five_reset=_FUTURE, seven_reset=_LATER),
    )

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert client.patches == []
    assert snapshot is not None
    assert snapshot.accounts[0].disabled is True
    assert snapshot.rate_limit_holds == ()


@pytest.mark.asyncio
async def test_poll_does_not_redisable_a_released_hold(monkeypatch) -> None:
    client = _MutableAuthClient()
    settings = _FakeSettings(
        claude_sidecar_quota_state_json=_hold_snapshot_json(
            SidecarRateLimitHold(name=_AUTH_NAME, until=_FUTURE, released=True),
            disabled=False,
        )
    )
    repo_holder, poller = _poll_with_usage(
        monkeypatch,
        settings,
        client,
        _usage(0.0, 70.0, five_reset=_FUTURE),
    )

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert client.patches == []
    assert snapshot is not None
    assert snapshot.accounts[0].disabled is False
    assert snapshot.rate_limit_holds == (SidecarRateLimitHold(name=_AUTH_NAME, until=_FUTURE, released=True),)


@pytest.mark.asyncio
async def test_poll_disables_again_when_reset_time_changes(monkeypatch) -> None:
    client = _MutableAuthClient()
    settings = _FakeSettings(
        claude_sidecar_quota_state_json=_hold_snapshot_json(
            SidecarRateLimitHold(name=_AUTH_NAME, until=_FUTURE, released=True),
            disabled=False,
        )
    )
    repo_holder, poller = _poll_with_usage(
        monkeypatch,
        settings,
        client,
        _usage(0.0, 70.0, five_reset=_LATER),
    )

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert client.patches == [(_AUTH_NAME, True)]
    assert snapshot is not None
    assert snapshot.rate_limit_holds == (SidecarRateLimitHold(name=_AUTH_NAME, until=_LATER, released=False),)


@pytest.mark.asyncio
async def test_poll_keeps_auth_enabled_when_disable_fails(monkeypatch) -> None:
    client = _MutableAuthClient()
    client.fail_disable = True
    repo_holder, poller = _poll_with_usage(
        monkeypatch,
        _FakeSettings(),
        client,
        _usage(0.0, 70.0, five_reset=_FUTURE),
    )

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert client.patches == []
    assert snapshot is not None
    assert snapshot.accounts[0].disabled is False
    assert snapshot.rate_limit_holds == ()


@pytest.mark.asyncio
async def test_poll_keeps_owned_hold_when_enable_fails(monkeypatch) -> None:
    client = _MutableAuthClient()
    client.disabled = True
    client.fail_enable = True
    hold = SidecarRateLimitHold(name=_AUTH_NAME, until=_FUTURE, released=False)
    repo_holder, poller = _poll_with_usage(
        monkeypatch,
        _FakeSettings(claude_sidecar_quota_state_json=_hold_snapshot_json(hold)),
        client,
        _usage(40.0, 70.0, five_reset=_FUTURE),
    )

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert client.patches == []
    assert snapshot is not None
    assert snapshot.accounts[0].disabled is True
    assert snapshot.rate_limit_holds == (hold,)


@pytest.mark.asyncio
async def test_poll_preserves_holds_when_listing_fails(monkeypatch) -> None:
    hold = SidecarRateLimitHold(name=_AUTH_NAME, until=_FUTURE, released=False)
    repo_holder: list[_FakeRepo] = []
    _patch_environment(
        monkeypatch,
        settings=_FakeSettings(claude_sidecar_quota_state_json=_hold_snapshot_json(hold)),
        client_factory=_UnauthorizedClient,
        repo_holder=repo_holder,
    )
    poller = ClaudeSidecarQuotaPoller(interval_seconds=60.0, enabled=True, _client_factory=_UnauthorizedClient)

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert snapshot is not None
    assert snapshot.status == "unauthorized"
    assert snapshot.accounts == ()
    assert snapshot.rate_limit_holds == (hold,)


@pytest.mark.asyncio
async def test_poll_keeps_operator_pause_recorded_during_the_usage_fetch(monkeypatch) -> None:
    client = _MutableAuthClient()
    client.disabled = False
    usage = _usage(0.0, 70.0, five_reset=_FUTURE)
    repo_holder, poller = _poll_with_usage(
        monkeypatch,
        _FakeSettings(claude_sidecar_quota_state_json=_hold_snapshot_json()),
        client,
        usage,
    )

    async def _fetch_then_pause(_client: object, auth_index: str) -> SidecarOAuthUsage:
        assert auth_index == "1"
        client.disabled = True
        return usage

    monkeypatch.setattr(quota_poller_module, "fetch_claude_oauth_usage", _fetch_then_pause)

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert client.patches == []
    assert snapshot is not None
    assert snapshot.accounts[0].disabled is True
    assert snapshot.rate_limit_holds == ()


@pytest.mark.asyncio
async def test_poll_keeps_hold_when_usage_is_unknown_before_reset(monkeypatch) -> None:
    from app.modules.claude_sidecar.oauth_usage import ClaudeOAuthUsageError

    hold = SidecarRateLimitHold(name=_AUTH_NAME, until=_FUTURE, released=False)
    stored = SidecarQuotaSnapshot(
        checked_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
        status="unreachable",
        message="down",
        accounts=(),
        rate_limit_holds=(hold,),
    )
    client = _MutableAuthClient()
    client.disabled = True
    repo_holder, poller = _poll_with_usage(
        monkeypatch,
        _FakeSettings(claude_sidecar_quota_state_json=snapshot_to_json(stored)),
        client,
        _usage(0.0, 70.0, five_reset=_FUTURE),
    )

    async def _fetch_fails(_client: object, _auth_index: str) -> SidecarOAuthUsage:
        raise ClaudeOAuthUsageError("Anthropic OAuth usage endpoint returned HTTP 429")

    monkeypatch.setattr(quota_poller_module, "fetch_claude_oauth_usage", _fetch_fails)

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert client.patches == []
    assert snapshot is not None
    assert snapshot.accounts[0].disabled is True
    assert snapshot.rate_limit_holds == (hold,)


@pytest.mark.asyncio
async def test_poll_stores_a_live_pause_over_an_enabled_snapshot(monkeypatch) -> None:
    client = _MutableAuthClient()
    client.disabled = True
    repo_holder, poller = _poll_with_usage(
        monkeypatch,
        _FakeSettings(claude_sidecar_quota_state_json=_hold_snapshot_json(disabled=False)),
        client,
        _usage(40.0, 70.0, five_reset=_FUTURE),
    )

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert client.patches == []
    assert snapshot is not None
    assert snapshot.accounts[0].disabled is True
    assert snapshot.rate_limit_holds == ()


@pytest.mark.asyncio
async def test_poll_stores_a_live_resume_over_a_disabled_snapshot(monkeypatch) -> None:
    client = _MutableAuthClient()
    client.disabled = False
    repo_holder, poller = _poll_with_usage(
        monkeypatch,
        _FakeSettings(claude_sidecar_quota_state_json=_hold_snapshot_json()),
        client,
        _usage(40.0, 70.0, five_reset=_FUTURE),
    )

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert client.patches == []
    assert snapshot is not None
    assert snapshot.accounts[0].disabled is False
    assert snapshot.rate_limit_holds == ()


@pytest.mark.asyncio
async def test_poll_keeps_hold_when_locked_listing_fails(monkeypatch) -> None:
    client = _MutableAuthClient()
    client.disabled = True
    client.fail_after_lists = 1
    hold = SidecarRateLimitHold(name=_AUTH_NAME, until=_FUTURE, released=False)
    repo_holder, poller = _poll_with_usage(
        monkeypatch,
        _FakeSettings(claude_sidecar_quota_state_json=_hold_snapshot_json(hold)),
        client,
        _usage(40.0, 70.0, five_reset=_FUTURE),
    )

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert client.patches == []
    assert snapshot is not None
    assert snapshot.accounts[0].disabled is True
    assert snapshot.rate_limit_holds == (hold,)


@pytest.mark.asyncio
async def test_poll_keeps_pause_saved_during_fetch_when_locked_listing_fails(monkeypatch) -> None:
    client = _MutableAuthClient()
    client.disabled = False
    client.fail_after_lists = 1
    settings = _FakeSettings(claude_sidecar_quota_state_json=_hold_snapshot_json(disabled=False))
    usage = _usage(40.0, 70.0, five_reset=_FUTURE)
    repo_holder, poller = _poll_with_usage(monkeypatch, settings, client, usage)

    async def _fetch_then_pause(_client: object, auth_index: str) -> SidecarOAuthUsage:
        assert auth_index == "1"
        stored = snapshot_from_json(settings.claude_sidecar_quota_state_json)
        assert stored is not None
        settings.claude_sidecar_quota_state_json = snapshot_to_json(
            replace(stored, accounts=tuple(replace(auth, disabled=True) for auth in stored.accounts))
        )
        client.disabled = True
        return usage

    monkeypatch.setattr(quota_poller_module, "fetch_claude_oauth_usage", _fetch_then_pause)

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert client.patches == []
    assert snapshot is not None
    assert snapshot.accounts[0].disabled is True
    assert snapshot.rate_limit_holds == ()


@pytest.mark.asyncio
async def test_poll_keeps_first_listing_when_locked_listing_fails_without_a_local_pause(
    monkeypatch,
) -> None:
    client = _MutableAuthClient()
    client.disabled = True
    client.fail_after_lists = 1
    repo_holder, poller = _poll_with_usage(
        monkeypatch,
        _FakeSettings(claude_sidecar_quota_state_json=_hold_snapshot_json(disabled=False)),
        client,
        _usage(40.0, 70.0, five_reset=_FUTURE),
    )

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert client.patches == []
    assert snapshot is not None
    assert snapshot.accounts[0].disabled is True
    assert snapshot.rate_limit_holds == ()


_OTHER_AUTH_NAME = "claude-b@example.com.json"


def _two_auth_snapshot_json(*, disabled: bool) -> str:
    primary = snapshot_from_json(_hold_snapshot_json(disabled=disabled))
    assert primary is not None
    other = replace(
        primary.accounts[0],
        name=_OTHER_AUTH_NAME,
        auth_index="2",
        email="b@example.com",
        disabled=disabled,
    )
    return snapshot_to_json(replace(primary, accounts=(primary.accounts[0], other)))


@pytest.mark.asyncio
async def test_poll_pause_during_fetch_does_not_reset_another_auth_when_listing_fails(
    monkeypatch,
) -> None:
    client = _MutableAuthClient()
    client.disabled = False
    client.fail_after_lists = 1
    client.extra_files = [
        {
            "name": _OTHER_AUTH_NAME,
            "provider": "claude",
            "email": "b@example.com",
            "auth_index": "2",
            "disabled": True,
            "status": "error",
            "status_message": "rate_limit_error",
        }
    ]
    settings = _FakeSettings(claude_sidecar_quota_state_json=_two_auth_snapshot_json(disabled=False))
    usage = _usage(40.0, 70.0, five_reset=_FUTURE)
    repo_holder, poller = _poll_with_usage(monkeypatch, settings, client, usage)

    async def _fetch_then_pause_primary(_client: object, auth_index: str) -> SidecarOAuthUsage:
        if auth_index != "1":
            return usage
        stored = snapshot_from_json(settings.claude_sidecar_quota_state_json)
        assert stored is not None
        settings.claude_sidecar_quota_state_json = snapshot_to_json(
            replace(
                stored,
                accounts=tuple(
                    replace(auth, disabled=True) if auth.name == _AUTH_NAME else auth for auth in stored.accounts
                ),
            )
        )
        client.disabled = True
        return usage

    monkeypatch.setattr(quota_poller_module, "fetch_claude_oauth_usage", _fetch_then_pause_primary)

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert snapshot is not None
    disabled_by_name = {auth.name: auth.disabled for auth in snapshot.accounts}
    assert disabled_by_name == {_AUTH_NAME: True, _OTHER_AUTH_NAME: True}
    assert snapshot.rate_limit_holds == ()


_XAI_NAME = "grok-a.json"


def _enable_xai_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.modules.claude_sidecar.grok_credits.XAI_QUOTA_INTEGRATION_ENABLED", True)


def _xai_file(*, disabled: bool = False) -> dict[str, Any]:
    return {
        "name": _XAI_NAME,
        "provider": "xai",
        "email": "grok@example.com",
        "auth_index": "x1",
        "disabled": disabled,
        "status": "active",
    }


class _GrokApiClient(_MutableAuthClient):
    def __init__(self) -> None:
        super().__init__()
        self.api_calls: list[dict[str, Any]] = []
        self.api_result: Any = "not-a-grpc-body"
        self.api_error: Exception | None = None
        self.extra_files = [_xai_file()]

    async def api_call(self, **kwargs: Any) -> Any:
        self.api_calls.append(kwargs)
        if self.api_error is not None:
            raise self.api_error
        return self.api_result

    async def patch_auth_file_disabled(self, name: str, disabled: bool) -> None:
        if disabled and self.fail_disable:
            raise ClaudeSidecarError(503, "disable failed")
        if not disabled and self.fail_enable:
            raise ClaudeSidecarError(503, "enable failed")
        self.patches.append((name, disabled))
        if name == _AUTH_NAME:
            self.disabled = disabled
            return
        self.extra_files = [
            {**entry, "disabled": disabled} if entry.get("name") == name else entry for entry in self.extra_files
        ]


def _stored_grok_snapshot() -> str:
    window = GrokCreditWindow(
        id="credits",
        label="week",
        kind="weekly",
        percent_used=89.0,
        percent_remaining=11.0,
        resets_at=_FUTURE,
    )
    xai = SidecarAuthQuota(
        name=_XAI_NAME,
        auth_index="x1",
        email="grok@example.com",
        provider="xai",
        status="active",
        status_message=None,
        disabled=False,
        unavailable=False,
        quota_exceeded=False,
        next_recover_at=None,
        model_states=(),
        success=0,
        failed=0,
        last_refresh=None,
        grok_credits=GrokCreditsQuota(windows=(window,), prepaid_credits=5),
    )
    claude = SidecarAuthQuota(
        name=_AUTH_NAME,
        auth_index="1",
        email="a@example.com",
        provider="claude",
        status="active",
        status_message=None,
        disabled=False,
        unavailable=False,
        quota_exceeded=False,
        next_recover_at=None,
        model_states=(),
        success=0,
        failed=0,
        last_refresh=None,
    )
    return snapshot_to_json(
        SidecarQuotaSnapshot(
            checked_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
            status="healthy",
            message=None,
            accounts=(claude, xai),
        )
    )


@pytest.mark.asyncio
async def test_poll_leaves_xai_alone_while_the_integration_is_off(monkeypatch) -> None:
    client = _GrokApiClient()

    async def _explode(**_kwargs: Any) -> Any:
        raise AssertionError("xAI quota polling must stay off")

    client.api_call = _explode  # type: ignore[method-assign]
    repo_holder, poller = _poll_with_usage(
        monkeypatch,
        _FakeSettings(),
        client,
        _usage(40.0, 70.0, five_reset=_FUTURE),
    )

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert snapshot is not None
    assert [account.provider for account in snapshot.accounts] == ["claude"]
    assert client.patches == []
    assert snapshot.accounts[0].oauth_usage is not None
    assert snapshot.accounts[0].oauth_usage.five_hour is not None
    assert snapshot.accounts[0].oauth_usage.five_hour.remaining_percent == 40.0


@pytest.mark.asyncio
async def test_poll_stores_grok_windows_from_the_api_call_passthrough(monkeypatch) -> None:
    _enable_xai_quota(monkeypatch)
    client = _GrokApiClient()
    client.api_result = _grpc_text(_message(1, _weekly_config()))
    repo_holder, poller = _poll_with_usage(
        monkeypatch,
        _FakeSettings(),
        client,
        _usage(40.0, 70.0, five_reset=_FUTURE),
    )

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert snapshot is not None
    assert client.patches == []
    assert len(client.api_calls) == 1
    assert client.api_calls[0]["auth_index"] == "x1"
    assert client.api_calls[0]["header"]["Authorization"] == "Bearer $TOKEN$"
    by_provider = {account.provider: account for account in snapshot.accounts}
    assert by_provider["claude"].oauth_usage is not None
    assert by_provider["claude"].oauth_usage.five_hour is not None
    assert by_provider["claude"].oauth_usage.five_hour.remaining_percent == 40.0
    credits = by_provider["xai"].grok_credits
    assert credits is not None
    assert credits.windows[0].id == "credits"
    assert credits.windows[0].percent_remaining == pytest.approx(62.5)
    assert credits.prepaid_credits == 42
    assert credits.observed_limit is None
    assert "observed_limit" not in repo_holder[-1].last_kwargs["claude_sidecar_quota_state_json"]


@pytest.mark.asyncio
async def test_poll_holds_only_the_xai_credential_on_free_usage_429(monkeypatch) -> None:
    _enable_xai_quota(monkeypatch)
    client = _GrokApiClient()
    client.api_error = ClaudeSidecarError(429, "limited", body='{"code":"free-usage-exhausted"}')
    repo_holder, poller = _poll_with_usage(
        monkeypatch,
        _FakeSettings(),
        client,
        _usage(40.0, 70.0, five_reset=_FUTURE),
    )

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert snapshot is not None
    assert client.patches == [(_XAI_NAME, True)]
    by_name = {account.name: account for account in snapshot.accounts}
    assert by_name[_AUTH_NAME].disabled is False
    assert by_name[_XAI_NAME].disabled is True
    assert snapshot.rate_limit_holds == (
        SidecarRateLimitHold(
            name=_XAI_NAME,
            until=snapshot.checked_at + timedelta(hours=24),
            released=False,
            provider="xai",
            kind="free-usage-exhausted",
            backoff_level=0,
        ),
    )


@pytest.mark.asyncio
async def test_poll_does_not_call_grok_for_an_unavailable_credential(monkeypatch) -> None:
    _enable_xai_quota(monkeypatch)
    client = _GrokApiClient()
    client.extra_files = [{**_xai_file(), "unavailable": True, "status": "error"}]
    client.api_result = _grpc_text(_message(1, _weekly_config()))
    repo_holder, poller = _poll_with_usage(
        monkeypatch,
        _FakeSettings(claude_sidecar_quota_state_json=_stored_grok_snapshot()),
        client,
        _usage(40.0, 70.0, five_reset=_FUTURE),
    )

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert snapshot is not None
    assert client.api_calls == []
    credits = next(account.grok_credits for account in snapshot.accounts if account.provider == "xai")
    assert credits is not None
    assert credits.windows[0].percent_remaining == 11.0
    assert client.patches == []


@pytest.mark.asyncio
async def test_poll_keeps_stored_grok_windows_when_the_passthrough_is_down(monkeypatch) -> None:
    _enable_xai_quota(monkeypatch)
    client = _GrokApiClient()
    client.api_error = ClaudeSidecarUnavailableError("connection refused")
    repo_holder, poller = _poll_with_usage(
        monkeypatch,
        _FakeSettings(claude_sidecar_quota_state_json=_stored_grok_snapshot()),
        client,
        _usage(12.0, 80.0, five_reset=_FUTURE),
    )

    await poller._poll_once()

    snapshot = _read_snapshot(repo_holder)
    assert snapshot is not None
    assert client.patches == []
    by_provider = {account.provider: account for account in snapshot.accounts}
    credits = by_provider["xai"].grok_credits
    assert credits is not None
    assert credits.windows[0].percent_remaining == 11.0
    assert credits.prepaid_credits == 5
    assert by_provider["claude"].oauth_usage is not None
    assert by_provider["claude"].oauth_usage.five_hour is not None
    assert by_provider["claude"].oauth_usage.five_hour.remaining_percent == 12.0
    assert snapshot.rate_limit_holds == ()
