"""Capacity routing for CLIProxyAPI credentials, with Codex selection unchanged."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.balancer.logic import AccountState, RoutingStrategy, select_account
from app.core.clients.claude_sidecar import (
    ClaudeSidecarClient,
    ClaudeSidecarConfig,
    ClaudeSidecarError,
    ClaudeSidecarUnavailableError,
    SidecarPrefix,
)
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.core.types import JsonValue
from app.db.models import AccountStatus, StickySessionKind
from app.modules.claude_sidecar.quota import (
    SidecarAuthQuota,
    SidecarModelQuota,
    SidecarQuotaSnapshot,
    SidecarQuotaStatus,
)
from app.modules.cliproxy_accounts.api_keys import (
    API_KEY_KINDS,
    ApiKeyRouteRow,
    api_key_account_id,
    api_key_route_identity,
    local_auth_index,
    set_api_key_prefix_if_empty,
)
from app.modules.cliproxy_accounts.management import ManagementResponse
from app.modules.proxy import claude_sidecar_dispatch
from app.modules.proxy import cliproxy_account_routing as routing
from app.modules.proxy.claude_sidecar_dispatch import build_sidecar_chat_payload
from app.modules.proxy.cliproxy_account_routing import (
    CliproxyCandidate,
    apply_cliproxy_account_route,
    candidate_serves_model,
    candidates_from_api_keys,
    candidates_from_snapshot,
    choose_cliproxy_route,
    cliproxy_log_attribution,
    rewrite_model_for_credential,
)
from app.modules.request_logs.mappers import cliproxy_credential_label

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_cliproxy_route_memory() -> None:
    routing._LAST_SELECTED.clear()
    routing._PREFIX_OVERLAY.clear()
    routing._LAST_GOOD_SNAPSHOT = None
    routing._LAST_GOOD_FORGOTTEN = False
    routing._LAST_GOOD_API_KEYS = ()
    routing._API_KEY_CACHE = None
    routing._MANAGEMENT_OUTAGE = None


def test_sidecar_chat_payload_forwards_the_resolved_model_id() -> None:
    payload = ChatCompletionsRequest.model_validate(
        {"model": "grok-4", "messages": [{"role": "user", "content": "hello"}]}
    )
    config = ClaudeSidecarConfig(
        enabled=True,
        base_url="http://127.0.0.1:8317",
        api_key="key",
        prefixes=(SidecarPrefix(prefix="claude", strip=False),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )

    forwarded = build_sidecar_chat_payload(payload, "grok-4", config)

    assert forwarded.body["model"] == "grok-4"
    assert not hasattr(claude_sidecar_dispatch, "prepare_cliproxy_account_route")


def test_codex_usage_weighted_still_prefers_the_lower_usage_account() -> None:
    low = AccountState(
        account_id="codex-low",
        status=AccountStatus.ACTIVE,
        used_percent=10.0,
        secondary_used_percent=10.0,
    )
    high = AccountState(
        account_id="codex-high",
        status=AccountStatus.ACTIVE,
        used_percent=80.0,
        secondary_used_percent=80.0,
    )

    selected = select_account((high, low), routing_strategy="usage_weighted")

    assert selected.account is not None
    assert selected.account.account_id == "codex-low"


def _candidate(
    account_id: str,
    prefix: str | None,
    *,
    used: float | None,
    priority: int = 0,
    weight: int = 1,
    status: AccountStatus = AccountStatus.ACTIVE,
    models: tuple[str, ...] = ("grok-4",),
    excluded: tuple[str, ...] = (),
    provider: str = "xai",
) -> CliproxyCandidate:
    return CliproxyCandidate(
        account_id=account_id,
        provider=provider,
        auth_index=account_id.rsplit(":", 1)[-1],
        name=f"{account_id}.json",
        prefix=prefix,
        priority=priority,
        weight=weight,
        models=models,
        excluded_models=excluded,
        family_fallback=not models,
        state=AccountState(
            account_id=account_id,
            status=status,
            used_percent=used,
            secondary_used_percent=used,
            plan_type=provider,
        ),
    )


async def _choose(
    candidates: list[CliproxyCandidate],
    *,
    sticky: bool = False,
    existing: str | None = None,
    model: str = "grok-4",
    strategy: RoutingStrategy = "usage_weighted",
) -> routing.CliproxyDispatchChoice | None:
    choice, _mutation = await choose_cliproxy_route(
        candidates,
        model=model,
        sticky_key="cliproxy:prompt_cache:thread-1" if sticky else None,
        sticky_kind=StickySessionKind.PROMPT_CACHE if sticky else None,
        sticky_repo=SimpleNamespace() if sticky else None,  # type: ignore[arg-type]
        sticky_enabled=sticky,
        existing_account_id=existing,
        routing_strategy=strategy,
        sticky_max_age_seconds=3600,
    )
    return choice


async def test_usage_weighted_prefers_measured_headroom_over_unknown_capacity() -> None:
    measured = _candidate("cliproxy:xai:busy", "busy", used=40.0)
    unknown = _candidate("cliproxy:xai:unknown", "unknown", used=None)

    choice = await _choose([unknown, measured])

    assert choice is not None
    assert choice.account_id == measured.account_id
    assert choice.route == "selected"
    assert choice.wire_model == "busy/grok-4"


async def test_unknown_capacity_serves_when_it_is_the_only_eligible_account() -> None:
    unknown = _candidate("cliproxy:xai:unknown", "unknown", used=None)

    choice = await _choose([unknown])

    assert choice is not None
    assert choice.wire_model == "unknown/grok-4"


async def test_non_positive_weight_is_excluded() -> None:
    paused_weight = _candidate("cliproxy:xai:zero", "zero", used=0.0, weight=0)
    serving = _candidate("cliproxy:xai:one", "one", used=50.0, weight=1)

    choice = await _choose([paused_weight, serving])

    assert choice is not None
    assert choice.account_id == serving.account_id


async def test_cold_selection_uses_the_highest_priority_tier_with_an_active_account() -> None:
    preferred = _candidate("cliproxy:xai:high", "high", used=80.0, priority=5)
    spare = _candidate("cliproxy:xai:low", "low", used=1.0, priority=0)
    exhausted_tier = _candidate(
        "cliproxy:xai:top",
        "top",
        used=100.0,
        priority=9,
        status=AccountStatus.QUOTA_EXCEEDED,
    )

    choice = await _choose([spare, exhausted_tier, preferred])

    assert choice is not None
    assert choice.account_id == preferred.account_id


async def test_sticky_hit_keeps_the_pinned_account_below_the_budget() -> None:
    pinned = _candidate("cliproxy:xai:pin", "pin", used=10.0, priority=0)
    fresher = _candidate("cliproxy:xai:fresh", "fresh", used=0.0, priority=5)

    choice = await _choose([fresher, pinned], sticky=True, existing=pinned.account_id)

    assert choice is not None
    assert choice.account_id == pinned.account_id
    assert choice.route == "sticky"
    assert choice.wire_model == "pin/grok-4"


async def test_sticky_rebinds_when_the_pin_is_over_budget() -> None:
    pinned = _candidate("cliproxy:xai:pin", "pin", used=96.0)
    spare = _candidate("cliproxy:xai:spare", "spare", used=10.0)

    choice = await _choose([pinned, spare], sticky=True, existing=pinned.account_id)

    assert choice is not None
    assert choice.account_id == spare.account_id
    assert choice.route == "rebind"
    assert choice.wire_model == "spare/grok-4"


async def test_sticky_rebinds_when_the_pin_is_quota_exhausted() -> None:
    pinned = _candidate("cliproxy:xai:pin", "pin", used=100.0, status=AccountStatus.QUOTA_EXCEEDED)
    spare = _candidate("cliproxy:xai:spare", "spare", used=20.0)

    choice = await _choose([pinned, spare], sticky=True, existing=pinned.account_id)

    assert choice is not None
    assert choice.account_id == spare.account_id
    assert choice.route == "rebind"


async def test_unknown_capacity_sticky_pin_stays_while_it_can_serve() -> None:
    pinned = _candidate("cliproxy:xai:pin", "pin", used=None)
    measured = _candidate("cliproxy:xai:measured", "measured", used=5.0)

    choice = await _choose([measured, pinned], sticky=True, existing=pinned.account_id)

    assert choice is not None
    assert choice.account_id == pinned.account_id
    assert choice.route == "sticky"


def _settings(*, enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        cliproxy_capacity_routing_enabled=enabled,
        claude_sidecar_base_url="http://127.0.0.1:8317",
        claude_sidecar_quota_state_json=None,
        sticky_threads_enabled=False,
        routing_strategy="usage_weighted",
        prefer_earlier_reset_accounts=False,
        prefer_earlier_reset_window="secondary",
        sticky_reallocation_primary_budget_threshold_pct=95.0,
        sticky_reallocation_secondary_budget_threshold_pct=100.0,
        http_responses_session_bridge_prompt_cache_idle_ttl_seconds=3600,
    )


def _install_settings(monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace) -> None:
    class _Cache:
        async def get(self) -> SimpleNamespace:
            return settings

    monkeypatch.setattr(routing, "get_settings_cache", lambda: _Cache())


async def test_dispatch_pins_the_chosen_prefix_on_a_stubbed_sidecar(monkeypatch: pytest.MonkeyPatch) -> None:
    chosen = _candidate("cliproxy:xai:acct1", "acct1", used=10.0)
    _install_settings(monkeypatch, _settings())
    monkeypatch.setattr(routing, "candidates_from_snapshot", lambda snapshot, *, now: [chosen])
    seen: list[str] = []

    class _Stub:
        async def chat_completion(self, body: dict[str, object]) -> dict[str, str]:
            model = body["model"]
            assert isinstance(model, str)
            seen.append(model)
            return {"id": "ok"}

    body: dict[str, object] = {"model": "grok-4"}
    choice = await apply_cliproxy_account_route(body, headers={}, client=None)  # type: ignore[arg-type]
    await claude_sidecar_dispatch._chat_completion_with_rebind(_Stub(), body)  # type: ignore[arg-type]

    assert choice is not None
    assert choice.wire_model == "acct1/grok-4"
    assert body["model"] == "acct1/grok-4"
    assert seen == ["acct1/grok-4"]
    assert cliproxy_log_attribution() == ("xai", "acct1", "selected")
    assert cliproxy_credential_label("xai", "acct1", "selected") == "xai/acct1 · selected"


async def test_dispatch_leaves_a_plain_model_when_routing_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_settings(monkeypatch, _settings(enabled=False))
    body: dict[str, object] = {"model": "grok-4"}

    choice = await apply_cliproxy_account_route(body, headers={}, client=None)  # type: ignore[arg-type]

    assert choice is None
    assert body["model"] == "grok-4"
    assert cliproxy_log_attribution() == (None, None, None)


async def test_dispatch_leaves_a_plain_model_when_selection_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_settings(monkeypatch, _settings())

    async def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("quota store unavailable")

    monkeypatch.setattr(routing, "_select_dispatch", _boom)
    body: dict[str, object] = {"model": "grok-4"}

    choice = await apply_cliproxy_account_route(body, headers={}, client=None)  # type: ignore[arg-type]

    assert choice is None
    assert body["model"] == "grok-4"


async def test_rebind_after_upstream_429_pins_the_other_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _candidate("cliproxy:xai:first", "first", used=10.0)
    second = _candidate("cliproxy:xai:second", "second", used=40.0)
    _install_settings(monkeypatch, _settings())
    monkeypatch.setattr(routing, "candidates_from_snapshot", lambda snapshot, *, now: [first, second])
    seen: list[str] = []
    calls = {"count": 0}

    class _Stub:
        async def chat_completion(self, body: dict[str, object]) -> dict[str, str]:
            model = body["model"]
            assert isinstance(model, str)
            seen.append(model)
            calls["count"] += 1
            if calls["count"] == 1:
                raise ClaudeSidecarError(429, "rate limited")
            return {"id": "ok"}

    body: dict[str, object] = {"model": "grok-4"}
    await apply_cliproxy_account_route(body, headers={}, client=None)  # type: ignore[arg-type]
    await claude_sidecar_dispatch._chat_completion_with_rebind(_Stub(), body)  # type: ignore[arg-type]

    assert seen == ["first/grok-4", "second/grok-4"]
    assert body["model"] == "second/grok-4"
    assert cliproxy_log_attribution() == ("xai", "second", "rebind")


def test_quota_model_states_block_a_model_without_becoming_the_catalog() -> None:
    snapshot = SidecarQuotaSnapshot(
        checked_at=datetime(2026, 10, 18, tzinfo=timezone.utc),
        status="healthy",
        message=None,
        accounts=(
            SidecarAuthQuota(
                name="grok-a.json",
                auth_index="x1",
                email="grok@example.com",
                status="active",
                status_message=None,
                disabled=False,
                unavailable=False,
                quota_exceeded=False,
                next_recover_at=None,
                model_states=(SidecarModelQuota(model="grok-4", quota_exceeded=True, next_recover_at=None),),
                success=0,
                failed=0,
                last_refresh=None,
                provider="xai",
                prefix="acct",
            ),
        ),
    )

    built = candidates_from_snapshot(snapshot, now=datetime(2026, 10, 18, tzinfo=timezone.utc))

    assert len(built) == 1
    assert built[0].models == ()
    assert built[0].blocked_models == frozenset({"grok-4"})
    assert candidate_serves_model(built[0], "grok-4") is False
    assert candidate_serves_model(built[0], "grok-4-fast") is True


async def test_discovered_models_replace_the_family_guess() -> None:
    routing._MODEL_CACHE = None
    snapshot = SidecarQuotaSnapshot(
        checked_at=datetime(2026, 10, 18, tzinfo=timezone.utc),
        status="healthy",
        message=None,
        accounts=(
            SidecarAuthQuota(
                name="grok-a.json",
                auth_index="x1",
                email="grok@example.com",
                status="active",
                status_message=None,
                disabled=False,
                unavailable=False,
                quota_exceeded=False,
                next_recover_at=None,
                model_states=(SidecarModelQuota(model="grok-4", quota_exceeded=True, next_recover_at=None),),
                success=0,
                failed=0,
                last_refresh=None,
                provider="xai",
                prefix="acct",
            ),
        ),
    )
    built = candidates_from_snapshot(snapshot, now=datetime(2026, 10, 18, tzinfo=timezone.utc))

    class _Catalog:
        async def list_auth_file_models(self, name: str) -> list[str]:
            assert name == "grok-a.json"
            return ["grok-4", "grok-4-fast"]

    attached = await routing._attach_discovered_models(built, _Catalog())  # type: ignore[arg-type]

    assert attached[0].models == ("grok-4", "grok-4-fast")
    assert attached[0].family_fallback is False
    assert candidate_serves_model(attached[0], "grok-4") is False
    assert candidate_serves_model(attached[0], "grok-4-fast") is True
    assert candidate_serves_model(attached[0], "grok-3") is False


def test_rewrite_keeps_a_namespaced_model_id() -> None:
    assert rewrite_model_for_credential("openrouter/auto", "lbabc") == "lbabc/openrouter/auto"
    assert (
        rewrite_model_for_credential(
            "lbother/openrouter/auto",
            "lbabc",
            known_prefixes=("lbother",),
        )
        == "lbabc/openrouter/auto"
    )
    assert rewrite_model_for_credential("vendor/model", "lbabc", known_prefixes=("lbabc",)) == "lbabc/vendor/model"


async def test_namespaced_catalog_ids_are_not_interchangeable() -> None:
    vendor = _candidate("cliproxy:xai:vendor", "pina", used=10.0, models=("vendor/model",))
    other = _candidate("cliproxy:xai:other", "pinb", used=0.0, models=("other/model",))

    choice = await _choose([other, vendor], model="vendor/model")

    assert choice is not None
    assert choice.account_id == vendor.account_id
    assert choice.wire_model == "pina/vendor/model"


async def test_round_robin_rotates_equally_used_credentials() -> None:
    first_account = _candidate("cliproxy:xai:a", "a", used=10.0)
    second_account = _candidate("cliproxy:xai:b", "b", used=10.0)

    first = await _choose([first_account, second_account], strategy="round_robin")
    second = await _choose([first_account, second_account], strategy="round_robin")

    assert first is not None and second is not None
    assert {first.account_id, second.account_id} == {first_account.account_id, second_account.account_id}
    assert first.account_id != second.account_id


async def test_remembered_prefix_skips_another_management_listing() -> None:
    bare = _candidate("cliproxy:xai:bare", None, used=10.0)
    routing._remember_prefix(bare.account_id, "kept")

    class _Listing:
        async def list_auth_files(self) -> list[object]:
            raise AssertionError("stale snapshot should reuse the remembered prefix")

    filled = await routing._fill_empty_prefixes([bare], "grok-4", _Listing())  # type: ignore[arg-type]

    assert filled[0].prefix == "kept"


def test_route_identity_survives_a_prefix_and_rejects_a_different_key() -> None:
    kind = API_KEY_KINDS["claude"]
    bare = {"api-key": "secret-a", "base-url": "https://api.anthropic.com"}
    filled = {**bare, "prefix": "lbabc", "models": [{"name": "m", "alias": "m"}], "priority": 3}
    other = {**bare, "api-key": "secret-b"}
    moved = {**bare, "base-url": "https://proxy.example"}

    assert api_key_route_identity(kind, bare) == api_key_route_identity(kind, filled)
    assert api_key_route_identity(kind, bare) != api_key_route_identity(kind, other)
    assert api_key_route_identity(kind, bare) != api_key_route_identity(kind, moved)
    assert api_key_account_id(kind, bare) != api_key_account_id(kind, filled)


class _V8Client:
    """CLIProxyAPI's v8 ``api-keys`` config API over one in-memory family."""

    def __init__(self, family: str, groups: list[dict[str, object]]) -> None:
        self.family = family
        self.groups = groups
        self.writes: list[object] = []

    async def config_v8_request(self, method: str, path: str, body: object, if_match: str | None) -> ManagementResponse:
        if method == "GET":
            assert path == "/v8/management/config/api-keys"
            return ManagementResponse(status=200, etag='"v1"', body={self.family: self.groups})
        assert path == f"/v8/management/config/api-keys/{self.family}"
        assert if_match == '"v1"'
        self.writes.append(body)
        return ManagementResponse(status=200, etag=None, body={"status": "ok"})


async def test_prefix_fill_follows_identity_after_the_list_shifts() -> None:
    kind = API_KEY_KINDS["claude"]
    client = _V8Client(
        "claude",
        [
            {"name": "b", "base-url": "https://api.anthropic.com", "keys": [{"api-key": "secret-b"}]},
            {"name": "a", "base-url": "https://api.anthropic.com", "keys": [{"api-key": "secret-a"}]},
        ],
    )

    identity = api_key_route_identity(kind, {"api-key": "secret-a", "base-url": "https://api.anthropic.com"})
    stored = await set_api_key_prefix_if_empty(
        client,  # type: ignore[arg-type]
        kind_slug="claude",
        route_identity=identity,
        prefix="lb-a",
    )

    assert stored == "lb-a"
    assert client.writes == [
        [
            {"name": "b", "base-url": "https://api.anthropic.com", "keys": [{"api-key": "secret-b"}]},
            {"name": "a", "base-url": "https://api.anthropic.com", "keys": [{"api-key": "secret-a"}], "prefix": "lb-a"},
        ]
    ]


async def test_prefix_fill_does_not_write_a_deleted_identity_onto_the_neighbor() -> None:
    kind = API_KEY_KINDS["claude"]
    client = _V8Client(
        "claude",
        [{"name": "b", "base-url": "https://api.anthropic.com", "keys": [{"api-key": "secret-b"}]}],
    )

    identity = api_key_route_identity(kind, {"api-key": "secret-a", "base-url": "https://api.anthropic.com"})
    stored = await set_api_key_prefix_if_empty(
        client,  # type: ignore[arg-type]
        kind_slug="claude",
        route_identity=identity,
        prefix="lb-a",
    )

    assert stored is None
    assert client.writes == []


def test_route_identity_is_cliproxyapi_auth_index() -> None:
    """Values read from a real CLIProxyAPI v8.0.32 binary (audit lab config)."""

    compat = API_KEY_KINDS["openai-compatibility"]
    claude = API_KEY_KINDS["claude"]
    lab_compat = {
        "base-url": "http://127.0.0.1:18080/v1",
        "api-key-entries": [{"api-key": "nv-key-a"}, {"api-key": "nv-key-b"}],
    }
    lab_claude = {"base-url": "http://127.0.0.1:18080", "api-key": "sk-ant-team"}
    assert (
        local_auth_index(compat, lab_compat)
        == hashlib.sha256(b"openai-compatibility:http://127.0.0.1:18080/v1+nv-key-a").hexdigest()[:16]
    )
    assert (
        local_auth_index(claude, lab_claude)
        == hashlib.sha256(b"claude-api-key:http://127.0.0.1:18080+sk-ant-team").hexdigest()[:16]
    )
    # A reported auth_index wins; without one the local digest is used.
    assert api_key_route_identity(claude, {**lab_claude, "auth-index": "abc"}) == "abc"
    assert api_key_route_identity(claude, lab_claude) == local_auth_index(claude, lab_claude)


def _api_key_row(index: int, route_identity: str, *, models: tuple[str, ...] = ("model-a",)) -> ApiKeyRouteRow:
    return ApiKeyRouteRow(
        kind="claude",
        index=index,
        name=f"key-{index}",
        prefix=None,
        disabled=False,
        models=models,
        auth_index=None,
        weight=None,
        priority=None,
        route_identity=route_identity,
    )


def test_remembered_prefix_does_not_follow_a_shifted_api_key_index() -> None:
    deleted = candidates_from_api_keys([_api_key_row(0, "identity-a", models=("model-a",))])[0]
    shifted = candidates_from_api_keys([_api_key_row(0, "identity-b", models=("model-b",))])[0]
    routing._remember_prefix(deleted.account_id, "from-a")

    filled = routing._with_remembered_prefixes([shifted])

    assert deleted.account_id != shifted.account_id
    assert filled[0].prefix is None


def test_operator_prefix_edit_drops_remembered_prefixes() -> None:
    routing._remember_prefix("cliproxy:xai:acct", "old")
    routing.forget_remembered_prefixes()

    assert routing._PREFIX_OVERLAY == {}


def _claude_snapshot(
    *accounts: SidecarAuthQuota,
    status: SidecarQuotaStatus = "healthy",
    message: str | None = None,
) -> SidecarQuotaSnapshot:
    return SidecarQuotaSnapshot(
        checked_at=datetime(2026, 10, 30, 7, 16, tzinfo=timezone.utc),
        status=status,
        message=message,
        accounts=accounts,
    )


def _claude_account(
    auth_index: str,
    *,
    prefix: str | None = "opus",
    excluded: tuple[str, ...] = (),
) -> SidecarAuthQuota:
    return SidecarAuthQuota(
        name=f"claude-{auth_index}.json",
        auth_index=auth_index,
        email=f"{auth_index}@example.com",
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
        provider="claude",
        excluded_models=excluded,
        prefix=prefix,
        priority=0,
        weight=1,
    )


class _ApiKeyClient(ClaudeSidecarClient):
    def __init__(self, rows: list[dict[str, JsonValue]] | None = None, *, error: Exception | None = None) -> None:
        super().__init__(
            ClaudeSidecarConfig(
                enabled=True,
                base_url="http://127.0.0.1:8317",
                api_key="key",
                prefixes=(),
                connect_timeout_seconds=8.0,
                request_timeout_seconds=600.0,
                models_cache_ttl_seconds=60.0,
            )
        )
        self.rows = rows if rows is not None else []
        self.error = error
        self.calls = 0

    async def list_api_keys(self) -> list[dict[str, JsonValue]]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.rows

    async def list_auth_files(self) -> list[Mapping[str, JsonValue]]:
        if self.error is not None:
            raise self.error
        return []

    async def config_v8_request(
        self,
        _method: str,
        _path: str,
        _body: JsonValue | None,
        _if_match: str | None,
    ) -> ManagementResponse:
        if self.error is not None:
            raise self.error
        return ManagementResponse(status=200, etag=None, body={})


async def test_management_403_keeps_routing_the_remembered_claude_credential(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    account = _claude_account("acct")
    settings = _settings()
    settings.claude_sidecar_quota_state_json = "stale"
    _install_settings(monkeypatch, settings)
    snapshots = iter(
        [
            _claude_snapshot(account),
            _claude_snapshot(status="unauthorized", message="IP banned due to too many failed attempts"),
        ]
    )
    monkeypatch.setattr(routing._SNAPSHOTS, "read", lambda _raw: next(snapshots))
    client = _ApiKeyClient(error=ClaudeSidecarError(403, "IP banned due to too many failed attempts"))
    body: dict[str, JsonValue] = {"model": "claude-opus-5-5"}

    first = await apply_cliproxy_account_route(body, client=client)
    routing._PREFIX_OVERLAY.clear()
    body["model"] = "claude-opus-5-5"
    with caplog.at_level("WARNING", logger=routing.logger.name):
        second = await apply_cliproxy_account_route(body, client=client)

    assert first is not None and second is not None
    assert first.wire_model == "opus/claude-opus-5-5"
    assert second.wire_model == "opus/claude-opus-5-5"
    assert second.account_id == first.account_id
    assert any(
        record.message == "CLIProxyAPI management unreachable: 403 IP banned; routing on last known credentials (1)"
        for record in caplog.records
    )


async def test_healthy_empty_listing_forgets_the_removed_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _claude_account("acct")
    settings = _settings()
    _install_settings(monkeypatch, settings)
    snapshots = iter(
        [
            _claude_snapshot(account),
            _claude_snapshot(),
            _claude_snapshot(status="unauthorized", message="IP banned"),
        ]
    )
    last = _claude_snapshot(status="unauthorized", message="IP banned")

    def _read(_raw: object) -> SidecarQuotaSnapshot:
        nonlocal last
        last = next(snapshots, last)
        return last

    monkeypatch.setattr(routing._SNAPSHOTS, "read", _read)
    client = _ApiKeyClient()
    body: dict[str, JsonValue] = {"model": "claude-opus-5-5"}

    remembered = await apply_cliproxy_account_route(body, client=client)
    body["model"] = "claude-opus-5-5"
    with pytest.raises(routing.CliproxyClaudeRouteRefused):
        await apply_cliproxy_account_route(body, client=client)
    body["model"] = "claude-opus-5-5"
    with pytest.raises(routing.CliproxyClaudeRouteRefused):
        await apply_cliproxy_account_route(body, client=client)

    assert remembered is not None
    assert remembered.wire_model == "opus/claude-opus-5-5"
    assert body["model"] == "claude-opus-5-5"


async def test_cold_management_outage_lets_cliproxy_choose_the_claude_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    _install_settings(monkeypatch, settings)
    monkeypatch.setattr(
        routing._SNAPSHOTS,
        "read",
        lambda _raw: _claude_snapshot(status="unreachable", message="connection refused"),
    )
    client = _ApiKeyClient(error=ClaudeSidecarError(403, "IP banned"))
    body: dict[str, JsonValue] = {"model": "claude-opus-5-5"}

    choice = await apply_cliproxy_account_route(body, client=client)

    assert choice is None
    assert body["model"] == "claude-opus-5-5"


async def test_management_timeout_keeps_routing_and_warns_once(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    account = _claude_account("acct")
    settings = _settings()
    _install_settings(monkeypatch, settings)
    state = {"failed": False}

    def _read(_raw: object) -> SidecarQuotaSnapshot:
        result = (
            _claude_snapshot(account, status="unreachable", message="timed out")
            if state["failed"]
            else _claude_snapshot(account)
        )
        return result

    class _TimingOut(_ApiKeyClient):
        def __init__(self) -> None:
            super().__init__()

        async def list_api_keys(self) -> list[dict[str, JsonValue]]:
            if state["failed"]:
                raise ClaudeSidecarUnavailableError("timed out talking to CLIProxyAPI management")
            return []

        async def list_auth_files(self) -> list[Mapping[str, JsonValue]]:
            if state["failed"]:
                raise ClaudeSidecarUnavailableError("timed out talking to CLIProxyAPI management")
            return []

        async def config_v8_request(
            self,
            _method: str,
            _path: str,
            _body: JsonValue | None,
            _if_match: str | None,
        ) -> ManagementResponse:
            if state["failed"]:
                raise ClaudeSidecarUnavailableError("timed out talking to CLIProxyAPI management")
            return ManagementResponse(status=200, etag=None, body={})

    monkeypatch.setattr(routing._SNAPSHOTS, "read", _read)
    client = _TimingOut()
    body: dict[str, JsonValue] = {"model": "claude-opus-5-5"}
    await apply_cliproxy_account_route(body, client=client)
    state["failed"] = True
    routing._PREFIX_OVERLAY.clear()
    body["model"] = "claude-opus-5-5"

    with caplog.at_level("WARNING", logger=routing.logger.name):
        routed = await apply_cliproxy_account_route(body, client=client)
        body["model"] = "claude-opus-5-5"
        again = await apply_cliproxy_account_route(body, client=client)

    assert routed is not None and again is not None
    assert routed.wire_model == "opus/claude-opus-5-5"
    warnings = [record.message for record in caplog.records if "management unreachable" in record.message]
    assert warnings == [
        "CLIProxyAPI management unreachable: unreachable: timed out; routing on last known credentials (1)"
    ]


async def test_management_outage_still_refuses_a_captain_excluded_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _claude_account("acct", excluded=("claude-opus-*",))
    settings = _settings()
    _install_settings(monkeypatch, settings)
    state = {"failed": False}

    def _read(_raw: object) -> SidecarQuotaSnapshot:
        if state["failed"]:
            return _claude_snapshot(account, status="unauthorized", message="IP banned")
        return _claude_snapshot(account)

    class _SwitchingClient(_ApiKeyClient):
        async def list_api_keys(self) -> list[dict[str, JsonValue]]:
            if state["failed"]:
                raise ClaudeSidecarError(403, "IP banned")
            return []

    monkeypatch.setattr(routing._SNAPSHOTS, "read", _read)
    client = _SwitchingClient()
    body: dict[str, JsonValue] = {"model": "claude-opus-5-5"}

    with pytest.raises(routing.CliproxyClaudeRouteRefused):
        await apply_cliproxy_account_route(body, client=client)
    state["failed"] = True
    body["model"] = "claude-opus-5-5"
    with pytest.raises(routing.CliproxyClaudeRouteRefused):
        await apply_cliproxy_account_route(body, client=client)
