"""Per-account CLIProxyAPI routing: sticky pool, prefix rewrite, failover."""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import Request

from app.core.balancer.logic import AccountState
from app.core.clients.claude_sidecar import ClaudeSidecarClient, ClaudeSidecarConfig, ClaudeSidecarError, SidecarPrefix
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.core.types import JsonValue
from app.db.models import Account, AccountStatus, StickySessionKind
from app.modules.claude_sidecar.quota import (
    GrokCreditsQuota,
    GrokCreditWindow,
    SidecarAuthQuota,
    SidecarQuotaSnapshot,
)
from app.modules.claude_sidecar.rate_limit_hold import XAI_LIMIT_FREE_USAGE
from app.modules.proxy import claude_sidecar_dispatch as sidecar_dispatch
from app.modules.proxy import cliproxy_account_routing as routing
from app.modules.proxy._load_balancer.sticky_selection import _select_with_stickiness
from app.modules.proxy.claude_sidecar_dispatch import (
    prepare_cliproxy_account_route,
    proxy_chat_to_sidecar,
    reset_claude_sidecar_cooldown_gate,
    sidecar_operation_with_credential_failover,
)
from app.modules.proxy.cliproxy_account_routing import (
    account_state_for_auth,
    apply_cliproxy_account_route,
    cliproxy_log_attribution,
    rewrite_model_for_credential,
)
from app.modules.proxy.sticky_repository import StickySessionsRepository


def _config() -> ClaudeSidecarConfig:
    return ClaudeSidecarConfig(
        enabled=True,
        base_url="http://127.0.0.1:8317",
        api_key="key",
        prefixes=(SidecarPrefix(prefix="claude", strip=False),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_route_choice() -> None:
    routing._CURRENT_CHOICE.set(None)
    reset_claude_sidecar_cooldown_gate()


def test_rewrite_replaces_one_segment_and_strip_false_does_not_unwrap() -> None:
    assert rewrite_model_for_credential("grok-4", "acct1", strip=False) == "acct1/grok-4"
    assert rewrite_model_for_credential("acct1/grok-4", "acct2", strip=False) == "acct2/grok-4"
    assert rewrite_model_for_credential("acct1/grok-4", "acct1", strip=False) == "acct1/grok-4"
    assert rewrite_model_for_credential("acct1/grok-4", None, strip=False) == "acct1/grok-4"
    assert rewrite_model_for_credential("grok-4", "acct/1", strip=False) == "grok-4"
    assert rewrite_model_for_credential("acct1/grok-4", "acct1", strip=True) == "grok-4"
    assert rewrite_model_for_credential("grok-4", "acct1", strip=True) == "grok-4"
    assert rewrite_model_for_credential("other/grok-4", "acct1", strip=True) == "other/grok-4"


def test_prefixed_claude_leaf_still_matches_capacity_gate() -> None:
    assert sidecar_dispatch._served_by_claude_auths({"model": "claude-sonnet-4-5"}) is True
    assert sidecar_dispatch._served_by_claude_auths({"model": "acct1/claude-sonnet-4-5"}) is True
    assert sidecar_dispatch._served_by_claude_auths({"model": "acct1/grok-4"}) is False


def _auth(
    name: str,
    auth_index: str,
    *,
    prefix: str,
    percent_used: float | None = None,
    exhausted: bool = False,
    provider: str = "xai",
) -> SidecarAuthQuota:
    credits = GrokCreditsQuota(observed_limit=XAI_LIMIT_FREE_USAGE) if exhausted else None
    if percent_used is not None:
        credits = GrokCreditsQuota(
            windows=(
                GrokCreditWindow(
                    id="credits",
                    label="credits",
                    kind="weekly",
                    percent_used=percent_used,
                    percent_remaining=max(0.0, 100.0 - percent_used),
                    resets_at=datetime.now(timezone.utc) + timedelta(days=3),
                ),
            )
        )
    return SidecarAuthQuota(
        name=name,
        auth_index=auth_index,
        email=None,
        status="ok",
        status_message=None,
        disabled=False,
        unavailable=False,
        quota_exceeded=False,
        next_recover_at=None,
        model_states=(),
        success=1,
        failed=0,
        last_refresh=None,
        provider=provider,
        prefix=prefix,
        grok_credits=credits,
    )


def test_xai_exhaustion_becomes_rate_limited_with_a_day_long_reset() -> None:
    now = datetime.now(timezone.utc)
    state = account_state_for_auth(
        _auth("grok-a.json", "idx-1", prefix="acct1", exhausted=True),
        holds=(),
        prefix="acct1",
        now=now,
    )

    assert state is not None
    assert state.status == AccountStatus.RATE_LIMITED
    assert state.used_percent == 100.0
    assert state.reset_at is not None
    assert state.reset_at - now.timestamp() >= 23 * 3600


class _StickyRepo:
    def __init__(self, existing: str | None) -> None:
        self.existing = existing
        self.upserts: list[tuple[str, str, StickySessionKind]] = []
        self.deletes: list[tuple[str, StickySessionKind]] = []

    async def get_account_id(
        self,
        key: str,
        *,
        kind: StickySessionKind,
        max_age_seconds: int | None = None,
    ) -> str | None:
        del key, kind, max_age_seconds
        return self.existing

    async def upsert(self, key: str, account_id: str, kind: StickySessionKind) -> None:
        self.upserts.append((key, account_id, kind))

    async def delete(self, key: str, kind: StickySessionKind) -> None:
        self.deletes.append((key, kind))


async def _select(
    states: Sequence[AccountState],
    *,
    existing: str | None,
    kind: StickySessionKind,
    sidecar_ids: frozenset[str] | None,
    account_ids_in_map: frozenset[str],
):
    repo = _StickyRepo(existing)
    outcome = await _select_with_stickiness(
        states=list(states),
        account_map={account_id: cast(Account, object()) for account_id in account_ids_in_map},
        sticky_key="thread",
        sticky_kind=kind,
        reallocate_sticky=False,
        sticky_max_age_seconds=600,
        prefer_earlier_reset_accounts=False,
        prefer_earlier_reset_window="secondary",
        routing_strategy="usage_weighted",
        sticky_repo=cast(StickySessionsRepository, repo),
        sidecar_account_ids=sidecar_ids,
    )
    return outcome, repo


@pytest.mark.asyncio
async def test_mixed_pool_persists_codex_sessions_and_refuses_sidecar_hard_pins() -> None:
    codex = AccountState("codex-1", AccountStatus.ACTIVE, used_percent=5.0)
    sidecar = AccountState("cliproxy:xai:idx-1", AccountStatus.ACTIVE, used_percent=40.0)
    sidecar_ids = frozenset({sidecar.account_id})

    kept, _repo = await _select(
        [codex, sidecar],
        existing=None,
        kind=StickySessionKind.CODEX_SESSION,
        sidecar_ids=sidecar_ids,
        account_ids_in_map=frozenset({codex.account_id, sidecar.account_id}),
    )
    assert kept.selection.account is not None
    assert kept.selection.account.account_id == codex.account_id
    assert kept.mutation is not None
    assert kept.mutation.account_id == codex.account_id

    sidecar_wins = AccountState("cliproxy:xai:idx-2", AccountStatus.ACTIVE, used_percent=1.0)
    denied, repo = await _select(
        [AccountState("codex-2", AccountStatus.ACTIVE, used_percent=80.0), sidecar_wins],
        existing=None,
        kind=StickySessionKind.CODEX_SESSION,
        sidecar_ids=frozenset({sidecar_wins.account_id}),
        account_ids_in_map=frozenset({"codex-2", sidecar_wins.account_id}),
    )
    assert denied.selection.account is not None
    assert denied.selection.account.account_id == sidecar_wins.account_id
    assert denied.mutation is None
    assert repo.upserts == []


@pytest.mark.asyncio
async def test_pure_codex_pool_still_persists_without_sidecar_ids() -> None:
    low = AccountState("codex-low", AccountStatus.ACTIVE, used_percent=4.0)
    high = AccountState("codex-high", AccountStatus.ACTIVE, used_percent=70.0)
    outcome, _repo = await _select(
        [high, low],
        existing=None,
        kind=StickySessionKind.CODEX_SESSION,
        sidecar_ids=None,
        account_ids_in_map=frozenset({low.account_id, high.account_id}),
    )

    assert outcome.selection.account is not None
    assert outcome.selection.account.account_id == low.account_id
    assert outcome.mutation is not None
    assert outcome.mutation.account_id == low.account_id


@pytest.mark.asyncio
async def test_xai_exhaustion_rebinds_and_a_near_limit_does_not_overwrite() -> None:
    now = datetime.now(timezone.utc)
    exhausted = account_state_for_auth(
        _auth("grok-a.json", "idx-1", prefix="acct1", exhausted=True),
        holds=(),
        prefix="acct1",
        now=now,
    )
    healthy = account_state_for_auth(
        _auth("grok-b.json", "idx-2", prefix="acct2", percent_used=12.0),
        holds=(),
        prefix="acct2",
        now=now,
    )
    assert exhausted is not None and healthy is not None
    sidecar_ids = frozenset({exhausted.account_id, healthy.account_id})

    rebound, _repo = await _select(
        [exhausted, healthy],
        existing=exhausted.account_id,
        kind=StickySessionKind.PROMPT_CACHE,
        sidecar_ids=sidecar_ids,
        account_ids_in_map=frozenset(),
    )
    assert rebound.selection.account is not None
    assert rebound.selection.account.account_id == healthy.account_id
    assert rebound.mutation is not None
    assert rebound.mutation.account_id == healthy.account_id

    near = AccountState(
        exhausted.account_id,
        AccountStatus.RATE_LIMITED,
        used_percent=100.0,
        reset_at=time.time() + 60,
    )
    preserved, repo = await _select(
        [near, healthy],
        existing=near.account_id,
        kind=StickySessionKind.PROMPT_CACHE,
        sidecar_ids=sidecar_ids,
        account_ids_in_map=frozenset(),
    )
    assert preserved.selection.account is not None
    assert preserved.selection.account.account_id == healthy.account_id
    assert preserved.mutation is None
    assert repo.upserts == []
    assert repo.deletes == []


class _Dialect:
    name = "sqlite"


class _Bind:
    dialect = _Dialect()


class _Session:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], object] = {}
        self.writes = 0

    def get_bind(self) -> _Bind:
        return _Bind()

    async def get(self, _model: object, ident: tuple[str, str]) -> object | None:
        return self.rows.get(ident)

    async def execute(self, statement: object) -> None:
        self.writes += 1
        params = cast(dict[str, object], statement.compile().params)  # type: ignore[attr-defined]
        key = cast(str, params["key"])
        kind = cast(str, params["kind"])
        self.rows[(key, kind)] = SimpleNamespace(
            key=key,
            kind=kind,
            account_id=params["account_id"],
            updated_at=params["updated_at"],
        )

    async def delete(self, row: object) -> None:
        key = cast(str, getattr(row, "key"))
        kind = cast(str, getattr(row, "kind"))
        self.rows.pop((key, kind), None)

    async def commit(self) -> None:
        return None


class _Pool:
    def __init__(self) -> None:
        self.accounts: list[SidecarAuthQuota] = []
        self.session = _Session()

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pool = self

        class _Reader:
            def read(self, _raw: str | None) -> SidecarQuotaSnapshot:
                return SidecarQuotaSnapshot(
                    checked_at=datetime.now(timezone.utc),
                    status="healthy",
                    message=None,
                    accounts=tuple(pool.accounts),
                )

        class _Prefixes:
            def __init__(self, _session: object) -> None:
                return None

            async def list_all(self) -> list[SimpleNamespace]:
                return [
                    SimpleNamespace(credential_name=auth.name, auth_index=auth.auth_index, prefix=auth.prefix)
                    for auth in pool.accounts
                ]

        class _Settings:
            claude_sidecar_quota_state_json = None
            http_responses_session_bridge_prompt_cache_idle_ttl_seconds = 600

        class _Cache:
            async def get(self) -> _Settings:
                return _Settings()

        class _Ctx:
            async def __aenter__(self) -> _Session:
                return pool.session

            async def __aexit__(self, *_exc: object) -> bool:
                return False

        monkeypatch.setattr(routing, "cliproxy_account_pool_enabled", lambda: True)
        monkeypatch.setattr(routing, "StoredSnapshotReader", _Reader)
        monkeypatch.setattr(routing, "CliproxyCredentialPrefixRepository", _Prefixes)
        monkeypatch.setattr(routing, "get_settings_cache", lambda: _Cache())
        monkeypatch.setattr(routing, "get_background_session", lambda: _Ctx())


@pytest.mark.asyncio
async def test_two_credential_stub_serves_acct1_then_acct2(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _Pool()
    pool.accounts = [
        _auth("grok-a.json", "idx-1", prefix="acct1", percent_used=10.0),
        _auth("grok-b.json", "idx-2", prefix="acct2", percent_used=40.0),
    ]
    pool.install(monkeypatch)
    body: dict[str, JsonValue] = {"model": "grok-4", "prompt_cache_key": "thread-9"}

    first = await apply_cliproxy_account_route(body, prompt_cache_key="thread-9")
    assert first is not None
    assert first.wire_model == "acct1/grok-4"
    assert body["model"] == "acct1/grok-4"
    assert cliproxy_log_attribution() == ("xai", "idx-1")

    pool.accounts = [
        _auth("grok-a.json", "idx-1", prefix="acct1", percent_used=30.0),
        _auth("grok-b.json", "idx-2", prefix="acct2", percent_used=5.0),
    ]
    sticky = await apply_cliproxy_account_route(body, prompt_cache_key="thread-9")
    assert sticky is not None
    assert sticky.wire_model == "acct1/grok-4"

    pool.accounts = [
        _auth("grok-a.json", "idx-1", prefix="acct1", exhausted=True),
        _auth("grok-b.json", "idx-2", prefix="acct2", percent_used=5.0),
    ]
    seen: list[str] = []

    async def operation() -> dict[str, bool]:
        seen.append(cast(str, body["model"]))
        if len(seen) == 1:
            raise ClaudeSidecarError(429, "quota")
        return {"ok": True}

    result = await sidecar_operation_with_credential_failover(body, operation)  # type: ignore[arg-type]
    assert result == {"ok": True}
    assert seen == ["acct1/grok-4", "acct2/grok-4"]
    assert cliproxy_log_attribution() == ("xai", "idx-2")


@pytest.mark.asyncio
async def test_same_owner_refresh_skips_the_sticky_write_inside_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = _Pool()
    pool.accounts = [
        _auth("grok-a.json", "idx-1", prefix="acct1", percent_used=10.0),
        _auth("grok-b.json", "idx-2", prefix="acct2", percent_used=40.0),
    ]
    pool.install(monkeypatch)
    body: dict[str, JsonValue] = {"model": "grok-4", "prompt_cache_key": "thread-9"}

    first = await apply_cliproxy_account_route(body, prompt_cache_key="thread-9")
    assert first is not None
    assert pool.session.writes == 1

    again = await apply_cliproxy_account_route(body, prompt_cache_key="thread-9")
    assert again is not None
    assert again.account_id == first.account_id
    assert pool.session.writes == 1

    row = next(iter(pool.session.rows.values()))
    row.updated_at = datetime.now(timezone.utc) - timedelta(seconds=30)
    refreshed = await apply_cliproxy_account_route(body, prompt_cache_key="thread-9")
    assert refreshed is not None
    assert refreshed.account_id == first.account_id
    assert pool.session.writes == 2


@pytest.mark.asyncio
async def test_client_error_does_not_rebind(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _Pool()
    pool.accounts = [
        _auth("grok-a.json", "idx-1", prefix="acct1", percent_used=10.0),
        _auth("grok-b.json", "idx-2", prefix="acct2", percent_used=40.0),
    ]
    pool.install(monkeypatch)
    body: dict[str, object] = {"model": "grok-4"}
    await prepare_cliproxy_account_route(body)  # type: ignore[arg-type]
    assert body["model"] == "acct1/grok-4"

    async def operation() -> None:
        raise ClaudeSidecarError(400, "bad request")

    with pytest.raises(ClaudeSidecarError):
        await sidecar_operation_with_credential_failover(body, operation)  # type: ignore[arg-type]
    assert body["model"] == "acct1/grok-4"


@pytest.mark.asyncio
async def test_unrecognized_model_stays_unprefixed_and_claude_skips_xai(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _Pool()
    pool.accounts = [
        _auth("grok-a.json", "idx-1", prefix="acct1", percent_used=10.0),
        _auth("claude-a.json", "idx-9", prefix="acct9", provider="claude"),
    ]
    pool.install(monkeypatch)

    gemini: dict[str, JsonValue] = {"model": "gemini-2.5-pro"}
    assert await apply_cliproxy_account_route(gemini, prompt_cache_key=None) is None
    assert gemini["model"] == "gemini-2.5-pro"
    assert cliproxy_log_attribution() == (None, None)

    claude: dict[str, JsonValue] = {"model": "claude-sonnet-4-5"}
    chosen = await apply_cliproxy_account_route(claude, prompt_cache_key=None)
    assert chosen is not None
    assert chosen.prefix == "acct9"
    assert claude["model"] == "acct9/claude-sonnet-4-5"
    assert cliproxy_log_attribution() == ("claude", "idx-9")


@pytest.mark.asyncio
async def test_pool_off_leaves_claude_model_and_skips_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> None:
        raise AssertionError("pool off touched storage")

    monkeypatch.setattr(routing, "get_background_session", _boom)
    body = {"model": "claude-sonnet-4-5"}
    assert await apply_cliproxy_account_route(body, prompt_cache_key="thread") is None
    assert body["model"] == "claude-sonnet-4-5"
    assert cliproxy_log_attribution() == (None, None)


@pytest.mark.asyncio
async def test_proxy_chat_forwards_the_selected_prefix_and_logs_it(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _Pool()
    pool.accounts = [
        _auth("grok-a.json", "idx-1", prefix="acct1", percent_used=10.0),
        _auth("grok-b.json", "idx-2", prefix="acct2", percent_used=40.0),
    ]
    pool.install(monkeypatch)
    seen: list[str] = []
    logged: dict[str, object] = {}

    class _Client:
        def __init__(self) -> None:
            self.config = _config()

        async def chat_completion(self, body: dict[str, object]) -> dict[str, object]:
            seen.append(cast(str, body["model"]))
            return {"usage": {"prompt_tokens": 2, "completion_tokens": 1}}

    class _Repo:
        def __init__(self, _session: object) -> None:
            return None

        async def add_log(self, **kwargs: object) -> None:
            logged.update(kwargs)

    class _Ctx:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_exc: object) -> bool:
            return False

    async def _cost(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(cost_usd=0.0, cost_source="catalog_calculated", price_status=None)

    monkeypatch.setattr(sidecar_dispatch, "get_background_session", lambda: _Ctx())
    monkeypatch.setattr(sidecar_dispatch, "RequestLogsRepository", _Repo)
    monkeypatch.setattr(sidecar_dispatch, "_sidecar_request_cost", _cost)
    monkeypatch.setattr(sidecar_dispatch, "_await_claude_capacity", _cost)

    request = Request({"type": "http", "asgi": {"version": "3.0"}, "method": "POST", "path": "/", "headers": []})
    payload = ChatCompletionsRequest.model_validate(
        {"model": "grok-4", "messages": [{"role": "user", "content": "hi"}], "stream": False}
    )
    response = await proxy_chat_to_sidecar(
        request,
        payload,
        effective_model="grok-4",
        api_key=None,
        reservation=None,
        rate_limit_headers={},
        sse_keepalive_interval_seconds=15,
        client=cast(ClaudeSidecarClient, _Client()),
    )

    assert response.status_code == 200
    assert seen == ["acct1/grok-4"]
    assert logged["sidecar_provider"] == "xai"
    assert logged["sidecar_auth_index"] == "idx-1"
    assert logged["model"] == "grok-4"


@pytest.mark.asyncio
async def test_proxy_chat_with_pool_off_forwards_the_unprefixed_model(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    class _Client:
        def __init__(self) -> None:
            self.config = _config()

        async def chat_completion(self, body: dict[str, object]) -> dict[str, object]:
            seen.append(cast(str, body["model"]))
            return {"usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    async def _cost(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(cost_usd=None, cost_source=None, price_status=None)

    async def _log(*_args: object, **kwargs: object) -> None:
        assert kwargs.get("sidecar_provider") is None
        assert kwargs.get("sidecar_auth_index") is None

    monkeypatch.setattr(sidecar_dispatch, "_sidecar_request_cost", _cost)
    monkeypatch.setattr(sidecar_dispatch, "_log_sidecar_request", _log)
    monkeypatch.setattr(sidecar_dispatch, "_await_claude_capacity", _cost)

    request = Request({"type": "http", "asgi": {"version": "3.0"}, "method": "POST", "path": "/", "headers": []})
    payload = ChatCompletionsRequest.model_validate(
        {"model": "claude-sonnet-4-5", "messages": [{"role": "user", "content": "hi"}], "stream": False}
    )
    response = await proxy_chat_to_sidecar(
        request,
        payload,
        effective_model="claude-sonnet-4-5",
        api_key=None,
        reservation=None,
        rate_limit_headers={},
        sse_keepalive_interval_seconds=15,
        client=cast(ClaudeSidecarClient, _Client()),
    )

    assert response.status_code == 200
    assert seen == ["claude-sonnet-4-5"]
