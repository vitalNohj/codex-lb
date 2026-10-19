"""Regression tests for CLIProxyAPI sticky coverage (audit clb-oa-12, PR-A + PR-C).

Each test names the audit finding it pins. Pins are stored in the real test
database so compare-and-set and purge run the production SQL.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy import select

from app.core.balancer.logic import AccountState
from app.core.clients.claude_sidecar import ClaudeSidecarClient, ClaudeSidecarError
from app.core.metrics import prometheus
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.core.openai.requests import ResponsesRequest
from app.core.types import JsonValue
from app.core.utils.time import utcnow
from app.db.models import AccountStatus, CliproxyStickySession, DashboardSettings, StickySessionKind
from app.db.session import get_background_session
from app.modules.api_keys.service import ApiKeyData
from app.modules.proxy import api as proxy_api
from app.modules.proxy import claude_sidecar_dispatch, responses_provider_dispatch
from app.modules.proxy import cliproxy_account_routing as routing
from app.modules.proxy.affinity import derive_content_prompt_cache_key
from app.modules.proxy.cliproxy_account_routing import (
    CliproxyCandidate,
    CliproxyStickyHints,
    apply_cliproxy_account_route,
    cliproxy_responses_sticky_hints,
    cliproxy_sticky_hints,
)
from app.modules.proxy.responses_chat_bridge import responses_to_chat_request
from app.modules.proxy.sticky_repository import StickySessionsRepository, cliproxy_sticky_max_age_seconds

pytestmark = pytest.mark.unit

MODEL = "claude-sonnet-4-5"


@pytest.fixture(autouse=True)
def _clear_route_memory() -> Iterator[None]:
    routing._LAST_SELECTED.clear()
    routing._PREFIX_OVERLAY.clear()
    routing._NO_CANDIDATE_WARNED.clear()
    routing.forget_cooldowns()
    yield
    routing.forget_cooldowns()


def _candidate(name: str, *, used: float | None, status: AccountStatus = AccountStatus.ACTIVE) -> CliproxyCandidate:
    account_id = f"cliproxy:claude:{name}"
    return CliproxyCandidate(
        account_id=account_id,
        provider="claude",
        auth_index=name,
        name=f"{name}.json",
        prefix=name,
        priority=0,
        weight=1,
        models=(MODEL,),
        excluded_models=(),
        family_fallback=False,
        state=AccountState(
            account_id=account_id,
            status=status,
            used_percent=used,
            secondary_used_percent=used,
            plan_type="claude",
        ),
    )


def _settings(**overrides: object) -> DashboardSettings:
    values: dict[str, object] = {
        "cliproxy_capacity_routing_enabled": True,
        "claude_sidecar_base_url": "http://127.0.0.1:8317",
        "claude_sidecar_quota_state_json": None,
        "sticky_threads_enabled": True,
        "routing_strategy": "usage_weighted",
        "prefer_earlier_reset_accounts": False,
        "prefer_earlier_reset_window": "secondary",
        "sticky_reallocation_primary_budget_threshold_pct": 95.0,
        "sticky_reallocation_secondary_budget_threshold_pct": 100.0,
        "http_responses_session_bridge_prompt_cache_idle_ttl_seconds": 3600,
    }
    values.update(overrides)
    return cast(DashboardSettings, SimpleNamespace(**values))


def _install(monkeypatch: pytest.MonkeyPatch, pool: list[CliproxyCandidate], **settings: object) -> None:
    resolved = _settings(**settings)

    class _Cache:
        async def get(self) -> DashboardSettings:
            return resolved

    monkeypatch.setattr(routing, "get_settings_cache", lambda: _Cache())
    monkeypatch.setattr(routing, "candidates_from_snapshot", lambda snapshot, *, now: list(pool))


def _chat(messages: list[dict[str, object]], **extra: object) -> ChatCompletionsRequest:
    return ChatCompletionsRequest.model_validate({"model": MODEL, "messages": messages, **extra})


def _conversation(turn: int) -> list[dict[str, object]]:
    """A growing conversation: same system text and first user message every turn."""

    messages: list[dict[str, object]] = [
        {"role": "system", "content": "You are a careful coding agent."},
        {"role": "user", "content": "Refactor the billing module."},
    ]
    for index in range(1, turn):
        messages.append({"role": "assistant", "content": f"step {index} done"})
        messages.append({"role": "user", "content": f"continue {index}"})
    return messages


async def _route(
    payload: ChatCompletionsRequest,
    *,
    headers: dict[str, str] | None = None,
    api_key_id: str | None = "key-1",
    derived: bool = False,
) -> routing.CliproxyDispatchChoice | None:
    body: dict[str, JsonValue] = {"model": payload.model}
    hints = cliproxy_sticky_hints(payload, api_key_id=api_key_id)
    if derived:
        hints = CliproxyStickyHints(body_session_id=hints.body_session_id, derived_key=hints.prompt_cache_key)
    return await apply_cliproxy_account_route(body, headers=headers or {}, client=None, hints=hints)


async def _pins() -> dict[str, str]:
    async with get_background_session() as session:
        rows = (await session.execute(select(CliproxyStickySession))).scalars().all()
        return {row.key: row.account_id for row in rows}


class _Counter:
    """Stands in for the Prometheus counter; prometheus_client is optional."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], float] = {}
        self._labels: tuple[str, str] = ("", "")

    def labels(self, *, outcome: str, key_source: str) -> _Counter:
        self._labels = (outcome, key_source)
        return self

    def inc(self) -> None:
        self.values[self._labels] = self.values.get(self._labels, 0.0) + 1


@pytest.fixture(autouse=True)
def _outcomes(monkeypatch: pytest.MonkeyPatch) -> _Counter:
    counter = _Counter()
    monkeypatch.setattr(routing, "cliproxy_route_outcome_total", counter)
    return counter


def test_s3_metric_is_registered_when_prometheus_is_available() -> None:
    assert "cliproxy_route_outcome_total" in prometheus.__all__
    if prometheus.PROMETHEUS_AVAILABLE:
        assert prometheus.cliproxy_route_outcome_total is not None


# --- S1: session identity ----------------------------------------------------


@pytest.mark.parametrize(
    "header",
    ["X-Claude-Code-Session-Id", "X-Session-Id", "X-Session-Affinity", "X-Kilo-Session-Id"],
)
async def test_s1_session_header_keeps_a_conversation_on_one_credential(
    db_setup: bool, monkeypatch: pytest.MonkeyPatch, header: str
) -> None:
    del db_setup
    _install(monkeypatch, [_candidate("a", used=None), _candidate("b", used=None), _candidate("c", used=None)])
    seen = set()
    for turn in range(1, 6):
        # A different first message each turn proves the header, not content, holds the pin.
        payload = _chat([{"role": "user", "content": f"unrelated {turn}"}])
        choice = await _route(payload, headers={header: "sess-123"})
        assert choice is not None
        assert choice.key_source == "session_header"
        seen.add(choice.account_id)
    assert len(seen) == 1
    assert list(await _pins()) == ["cliproxy:session:sess-123"]


@pytest.mark.parametrize(
    "extra",
    [{"session_id": "body-sess"}, {"metadata": {"session_id": "body-sess"}}, {"sessionId": "body-sess"}],
)
async def test_s1_body_session_id_pins_the_conversation(
    db_setup: bool, monkeypatch: pytest.MonkeyPatch, extra: dict[str, object]
) -> None:
    del db_setup
    _install(monkeypatch, [_candidate("a", used=None), _candidate("b", used=None)])
    first = await _route(_chat(_conversation(1), **extra))
    second = await _route(_chat(_conversation(3), **extra))
    assert first is not None and second is not None
    assert first.key_source == "body_session_id"
    assert second.account_id == first.account_id
    assert second.route == "sticky"


async def test_s1_derived_key_pins_a_keyless_conversation(db_setup: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lab scenario 3: no key, no header; every turn must stay on one account."""

    del db_setup
    _install(monkeypatch, [_candidate(name, used=None) for name in ("a", "b", "c", "d")])
    seen = []
    for turn in range(1, 8):
        choice = await _route(_chat(_conversation(turn)))
        assert choice is not None
        assert choice.key_source == "derived"
        seen.append(choice.account_id)
    assert len(set(seen)) == 1
    pins = await _pins()
    assert len(pins) == 1
    assert next(iter(pins)).startswith("cliproxy:derived:")


async def test_s1_derived_key_separates_api_keys_and_conversations(
    db_setup: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    del db_setup
    _install(monkeypatch, [_candidate("a", used=None), _candidate("b", used=None)])
    await _route(_chat(_conversation(1)), api_key_id="key-1")
    await _route(_chat(_conversation(1)), api_key_id="key-2")
    await _route(_chat([{"role": "user", "content": "another task"}]), api_key_id="key-1")
    assert len(await _pins()) == 3


async def test_s1_derived_key_matches_the_codex_recipe() -> None:
    messages = _conversation(2)
    payload = _chat(messages)
    hints = cliproxy_sticky_hints(payload, api_key_id="key-1")
    assert hints.derived_key == derive_content_prompt_cache_key(
        model=MODEL, instructions=None, input_value=messages, api_key_id="key-1"
    )
    # Later turns only append, so the key does not change.
    assert cliproxy_sticky_hints(_chat(_conversation(5)), api_key_id="key-1").derived_key == hints.derived_key


async def test_s1_nothing_to_hash_stays_unpinned(db_setup: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    del db_setup
    _install(monkeypatch, [_candidate("a", used=None)])
    choice = await _route(_chat([{"role": "assistant", "content": "x"}]), api_key_id=None)
    assert choice is not None
    assert choice.sticky_key is None
    assert choice.key_source == "none"
    assert await _pins() == {}


async def test_s1_derivation_switch_off_stays_unpinned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        routing, "get_settings", lambda: SimpleNamespace(openai_prompt_cache_key_derivation_enabled=False)
    )
    assert cliproxy_sticky_hints(_chat(_conversation(1)), api_key_id="key-1").derived_key is None


def test_s1_identity_order_matches_cliproxyapi() -> None:
    hints = CliproxyStickyHints(prompt_cache_key="pck", body_session_id="body", derived_key="derived")
    headers = {"X-Claude-Code-Session-Id": "claude-sess"}
    assert routing._resolve_sticky_identity(hints, headers, sticky_enabled=True).source == "prompt_cache_key"
    no_key = CliproxyStickyHints(body_session_id="body", derived_key="derived")
    assert routing._resolve_sticky_identity(no_key, headers, sticky_enabled=True).source == "session_header"
    assert routing._resolve_sticky_identity(no_key, {}, sticky_enabled=True).source == "body_session_id"
    only_derived = CliproxyStickyHints(derived_key="derived")
    assert routing._resolve_sticky_identity(only_derived, {}, sticky_enabled=True).source == "derived"
    assert routing._resolve_sticky_identity(hints, headers, sticky_enabled=False).source == "disabled"


def test_s1_a_bridge_derived_key_ranks_below_session_headers() -> None:
    payload = _responses(prompt_cache_key="bridge-derived")
    hints = cliproxy_responses_sticky_hints(payload, prompt_cache_key_derived=True)
    assert hints.prompt_cache_key is None
    assert hints.derived_key == "bridge-derived"
    identity = routing._resolve_sticky_identity(hints, {"X-Session-Id": "sess"}, sticky_enabled=True)
    assert identity.source == "session_header"


@pytest.mark.parametrize(
    "extra",
    [{"session_id": "resp-sess"}, {"sessionId": "resp-sess"}, {"metadata": {"session_id": "resp-sess"}}],
)
def test_s1_responses_body_session_id_outranks_a_bridge_derived_key(extra: dict[str, object]) -> None:
    """The chat translation keeps only prompt_cache_key; body session ids are read before it."""

    payload = _responses(prompt_cache_key="bridge-derived", **extra)
    hints = cliproxy_responses_sticky_hints(payload, prompt_cache_key_derived=True)
    identity = routing._resolve_sticky_identity(hints, {}, sticky_enabled=True)
    assert identity.source == "body_session_id"
    assert identity.key == "cliproxy:session:resp-sess"


def test_s1_responses_client_key_keeps_its_rank() -> None:
    payload = _responses(prompt_cache_key="client-key", session_id="resp-sess")
    hints = cliproxy_responses_sticky_hints(payload, prompt_cache_key_derived=False)
    assert routing._resolve_sticky_identity(hints, {}, sticky_enabled=True).source == "prompt_cache_key"


async def test_s1_responses_bridge_routes_on_the_hints_read_before_translation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end through the bridge: the sidecar route sees the Responses session id."""

    seen: list[CliproxyStickyHints | None] = []

    async def fake_sidecar(request: object, payload: ChatCompletionsRequest, **kwargs: Any) -> object:
        del request, payload
        seen.append(kwargs.get("sticky_hints"))
        raise RuntimeError("stop")

    monkeypatch.setattr(responses_provider_dispatch, "proxy_chat_to_sidecar", fake_sidecar)
    payload = _responses(metadata={"session_id": "resp-sess"})
    hints = cliproxy_responses_sticky_hints(payload, prompt_cache_key_derived=False)
    with pytest.raises(RuntimeError, match="stop"):
        await responses_provider_dispatch.dispatch_responses_via_chat_provider(
            cast(Any, None),
            responses_to_chat_request(payload, MODEL),
            provider="claude",
            effective_model=MODEL,
            wire_model=MODEL,
            api_key=None,
            reservation=None,
            rate_limit_headers={},
            sse_keepalive_interval_seconds=1.0,
            cursor_compat=False,
            client=object(),
            sticky_hints=hints,
        )
    assert seen == [hints]
    assert seen[0] is not None and seen[0].body_session_id == "resp-sess"


def test_s1_client_request_id_is_not_a_session() -> None:
    identity = routing._resolve_sticky_identity(
        CliproxyStickyHints(), {"X-Client-Request-Id": "per-request"}, sticky_enabled=True
    )
    assert identity.key is None


def test_s1_long_session_ids_are_hashed() -> None:
    identity = routing._resolve_sticky_identity(
        CliproxyStickyHints(body_session_id="s" * 1000), {}, sticky_enabled=True
    )
    assert identity.key is not None
    assert identity.key.startswith("cliproxy:session:sha256:")


# --- S2 / T1: Responses bridge -----------------------------------------------


def _responses(**overrides: object) -> ResponsesRequest:
    data: dict[str, object] = {
        "model": MODEL,
        "instructions": "You are a careful coding agent.",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "Refactor the billing module."}]}],
    }
    data.update(overrides)
    return ResponsesRequest.model_validate(data)


def test_s2_bridge_forwards_prompt_cache_key() -> None:
    chat = responses_to_chat_request(_responses(prompt_cache_key="thread-9"), MODEL)
    assert (chat.model_extra or {}).get("prompt_cache_key") == "thread-9"
    assert cliproxy_sticky_hints(chat, api_key_id=None).prompt_cache_key == "thread-9"


def test_s2_bridge_without_a_key_adds_none() -> None:
    chat = responses_to_chat_request(_responses(), MODEL)
    assert "prompt_cache_key" not in (chat.model_extra or {})


def test_s2_keyless_responses_request_gets_a_stable_derived_key() -> None:
    api_key = cast(ApiKeyData, SimpleNamespace(id="key-1"))
    first = _responses()
    later = _responses(
        input=[
            {"role": "user", "content": [{"type": "input_text", "text": "Refactor the billing module."}]},
            {"role": "assistant", "content": [{"type": "output_text", "text": "done"}]},
            {"role": "user", "content": [{"type": "input_text", "text": "continue"}]},
        ]
    )
    assert proxy_api._derive_chat_provider_prompt_cache_key(first, api_key) is True
    assert proxy_api._derive_chat_provider_prompt_cache_key(later, api_key) is True
    assert first.prompt_cache_key is not None
    assert first.prompt_cache_key == later.prompt_cache_key
    chat = responses_to_chat_request(first, MODEL)
    assert (chat.model_extra or {}).get("prompt_cache_key") == first.prompt_cache_key


def test_s2_client_key_is_kept_and_not_marked_derived() -> None:
    payload = _responses(prompt_cache_key="  client-key  ")
    assert proxy_api._derive_chat_provider_prompt_cache_key(payload, None) is False
    assert payload.prompt_cache_key == "client-key"


# --- S3: route outcome metric and log ------------------------------------------


async def test_s3_route_outcomes_are_counted_and_logged(
    db_setup: bool, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, _outcomes: _Counter
) -> None:
    del db_setup
    _install(monkeypatch, [_candidate("a", used=None)])
    caplog.set_level(logging.INFO, logger=routing.__name__)

    await _route(_chat(_conversation(1)), headers={"X-Session-Id": "s3"})
    await _route(_chat(_conversation(2)), headers={"X-Session-Id": "s3"})

    assert _outcomes.values == {("selected", "session_header"): 1, ("sticky", "session_header"): 1}
    assert "cliproxy_route_outcome outcome=sticky key_source=session_header" in caplog.text


async def test_s3_unpinned_and_fail_open_are_visible(
    db_setup: bool, monkeypatch: pytest.MonkeyPatch, _outcomes: _Counter
) -> None:
    del db_setup
    _install(monkeypatch, [_candidate("a", used=None)], sticky_threads_enabled=False)
    await _route(_chat(_conversation(1)))
    assert _outcomes.values == {("unpinned_no_key", "disabled"): 1}

    async def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("store down")

    monkeypatch.setattr(routing, "_select_dispatch", _boom)
    body: dict[str, JsonValue] = {"model": MODEL}
    assert await apply_cliproxy_account_route(body, headers={}, client=None) is None
    assert body["model"] == MODEL
    assert _outcomes.values[("fail_open", "disabled")] == 1


# --- S4: neutral unknown capacity and missing prefixes -------------------------


async def test_s4_unmeasured_account_is_neutral_not_starved() -> None:
    unknown = _candidate("unknown", used=None)
    busy = _candidate("busy", used=80.0)
    light = _candidate("light", used=10.0)

    async def pick(pool: list[CliproxyCandidate]) -> str | None:
        choice, _ = await routing.choose_cliproxy_route(
            pool, model=MODEL, sticky_key=None, sticky_kind=None, sticky_repo=None, sticky_enabled=False
        )
        return choice.account_id if choice else None

    assert await pick([busy, unknown]) == unknown.account_id
    assert await pick([unknown, light]) == light.account_id


async def test_s4_no_prefixed_candidate_warns_once(
    db_setup: bool, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, _outcomes: _Counter
) -> None:
    del db_setup
    bare = routing.replace(_candidate("bare", used=None), prefix=None)
    _install(monkeypatch, [bare])

    async def _no_fill(candidates: list[CliproxyCandidate], *_args: object) -> list[CliproxyCandidate]:
        return candidates

    monkeypatch.setattr(routing, "_fill_empty_prefixes", _no_fill)
    caplog.set_level(logging.WARNING, logger=routing.__name__)
    for _ in range(3):
        assert await _route(_chat(_conversation(1)), headers={"X-Session-Id": "s4"}) is None
    warnings = [r for r in caplog.records if "found no prefixed credential" in r.getMessage()]
    assert len(warnings) == 1
    assert _outcomes.values == {("no_candidate", "session_header"): 3}


# --- S5: transient failure keeps the warm pin -------------------------------------


class _FailOnce:
    def __init__(self, failing_prefix: str, status: int) -> None:
        self.failing_prefix = failing_prefix
        self.status = status
        self.seen: list[str] = []

    async def chat_completion(self, body: dict[str, JsonValue]) -> dict[str, str]:
        model = str(body["model"])
        self.seen.append(model)
        if model.startswith(f"{self.failing_prefix}/") and self.status:
            status, self.status = self.status, 0
            raise ClaudeSidecarError(status, "transient")
        return {"id": "ok"}


async def _turn(client: _FailOnce, turn: int) -> str:
    body: dict[str, JsonValue] = {"model": MODEL}
    payload = _chat(_conversation(turn))
    await apply_cliproxy_account_route(
        body,
        headers={"X-Session-Id": "s5"},
        client=None,
        hints=cliproxy_sticky_hints(payload, api_key_id="key-1"),
    )
    await claude_sidecar_dispatch._chat_completion_with_rebind(cast(ClaudeSidecarClient, client), body)
    return str(body["model"]).split("/", 1)[0]


@pytest.mark.parametrize("status", [429, 401, 403])
async def test_s5_transient_failure_returns_to_the_warm_account(
    db_setup: bool, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """Lab scenarios 4a/4b: the detour is one request, then the warm pin serves again."""

    del db_setup
    _install(monkeypatch, [_candidate("a", used=10.0), _candidate("b", used=40.0), _candidate("c", used=50.0)])
    client = _FailOnce("never", 0)
    warm = await _turn(client, 1)
    assert warm == "a"

    client.failing_prefix, client.status = warm, status
    detour = await _turn(client, 2)
    assert detour != warm
    pins = await _pins()
    assert pins["cliproxy:session:s5"] == "cliproxy:claude:a"
    assert pins[routing._fallback_key("cliproxy:session:s5")] == f"cliproxy:claude:{detour}"

    # While the warm account cools down the conversation stays on the same spare.
    assert await _turn(client, 3) == detour
    assert await _turn(client, 4) == detour

    # Cooldown over: back to the warm account, pin never moved.
    routing.forget_cooldowns()
    assert await _turn(client, 5) == warm
    assert (await _pins())["cliproxy:session:s5"] == "cliproxy:claude:a"


async def test_s5_a_pin_created_by_the_failing_request_moves(db_setup: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    del db_setup
    _install(monkeypatch, [_candidate("a", used=10.0), _candidate("b", used=40.0)])
    client = _FailOnce("a", 429)
    assert await _turn(client, 1) == "b"
    assert (await _pins())["cliproxy:session:s5"] == "cliproxy:claude:b"
    assert await _turn(client, 2) == "b"


async def test_s5_quota_exhaustion_still_moves_the_pin(db_setup: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    del db_setup
    pool = [_candidate("a", used=10.0), _candidate("b", used=40.0)]
    _install(monkeypatch, pool)
    client = _FailOnce("never", 0)
    assert await _turn(client, 1) == "a"
    pool[0] = _candidate("a", used=100.0, status=AccountStatus.QUOTA_EXCEEDED)
    assert await _turn(client, 2) == "b"
    assert (await _pins())["cliproxy:session:s5"] == "cliproxy:claude:b"


async def test_s5_a_cooling_pin_that_runs_out_of_quota_moves(db_setup: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    """Kody: a cooling pin is kept only while its credential can still serve."""

    del db_setup
    pool = [_candidate("a", used=10.0), _candidate("b", used=40.0), _candidate("c", used=50.0)]
    _install(monkeypatch, pool)
    client = _FailOnce("never", 0)
    assert await _turn(client, 1) == "a"
    client.failing_prefix, client.status = "a", 429
    detour = await _turn(client, 2)
    assert detour != "a"
    assert (await _pins())["cliproxy:session:s5"] == "cliproxy:claude:a"

    # Still cooling, but now quota-exhausted: the pin moves instead of waiting.
    pool[0] = _candidate("a", used=100.0, status=AccountStatus.QUOTA_EXCEEDED)
    client.failing_prefix = "never"
    moved = await _turn(client, 3)
    assert moved != "a"
    assert (await _pins())["cliproxy:session:s5"] == f"cliproxy:claude:{moved}"


@pytest.mark.parametrize(
    "status",
    [AccountStatus.PAUSED, AccountStatus.QUOTA_EXCEEDED, AccountStatus.REAUTH_REQUIRED, AccountStatus.DEACTIVATED],
)
def test_s5_cooling_is_skipped_only_for_a_selectable_spare(status: AccountStatus) -> None:
    """Kody: a spare the balancer would refuse does not displace the cooling credential."""

    cooling = _candidate("a", used=10.0)
    spare = _candidate("b", used=40.0, status=status)
    routing._start_cooldown(cooling.account_id)
    assert routing._without_cooling([cooling, spare], MODEL) == [cooling, spare]
    healthy = _candidate("c", used=50.0)
    assert routing._without_cooling([cooling, spare, healthy], MODEL) == [spare, healthy]


async def test_s5_cooling_last_resort_serves_when_the_spare_is_paused(
    db_setup: bool, monkeypatch: pytest.MonkeyPatch, _outcomes: _Counter
) -> None:
    del db_setup
    _install(monkeypatch, [_candidate("a", used=10.0), _candidate("b", used=40.0, status=AccountStatus.PAUSED)])
    routing._start_cooldown("cliproxy:claude:a")
    # Pinned (session header) and unpinned (derivation off) paths both keep serving.
    choice = await _route(_chat(_conversation(1)), headers={"X-Session-Id": "s5-last"})
    assert choice is not None and choice.account_id == "cliproxy:claude:a"
    _install(
        monkeypatch,
        [_candidate("a", used=10.0), _candidate("b", used=40.0, status=AccountStatus.PAUSED)],
        sticky_threads_enabled=False,
    )
    choice = await _route(_chat(_conversation(1)))
    assert choice is not None and choice.account_id == "cliproxy:claude:a"
    assert not any(outcome in {"fail_open", "no_candidate"} for outcome, _source in _outcomes.values)


@pytest.mark.parametrize("status", [AccountStatus.REAUTH_REQUIRED, AccountStatus.PAUSED, AccountStatus.DEACTIVATED])
def test_s5_unusable_cooling_pins_are_not_kept(status: AccountStatus) -> None:
    pool = [_candidate("a", used=10.0, status=status), _candidate("b", used=40.0)]
    assert routing._pin_still_usable(pool, "cliproxy:claude:a", MODEL) is False
    assert routing._pin_still_usable(pool, "cliproxy:claude:b", MODEL) is True
    assert routing._pin_still_usable(pool, "cliproxy:claude:gone", MODEL) is False


def test_s5_fallback_keys_cannot_collide_with_client_identities() -> None:
    """nohjbot F1: no client session id resolves to another conversation's fallback row."""

    primary = routing._resolve_sticky_identity(CliproxyStickyHints(), {"X-Session-Id": "s"}, sticky_enabled=True)
    assert primary.key is not None
    fallback = routing._fallback_key(primary.key)
    assert fallback.startswith("cliproxy:fallback:")
    for crafted in ("s#fallback", fallback, fallback.split(":", 2)[2]):
        for hints, headers in (
            (CliproxyStickyHints(), {"X-Session-Id": crafted}),
            (CliproxyStickyHints(prompt_cache_key=crafted), {}),
            (CliproxyStickyHints(body_session_id=crafted), {}),
            (CliproxyStickyHints(derived_key=crafted), {}),
        ):
            identity = routing._resolve_sticky_identity(hints, headers, sticky_enabled=True)
            assert identity.key != fallback
            assert identity.key is not None and not identity.key.startswith("cliproxy:fallback:")
    assert routing._fallback_key("cliproxy:session:t") != fallback


# --- S6: atomic first pin --------------------------------------------------------


async def test_s6_concurrent_first_turns_share_one_pin(db_setup: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lab scenario 7: parallel first turns of one conversation land on one credential."""

    del db_setup
    _install(monkeypatch, [_candidate(name, used=None) for name in ("a", "b", "c", "d")])
    real_choose = routing.choose_cliproxy_route
    barrier = asyncio.Barrier(6)
    rotation = iter(["a", "b", "c", "d", "a", "b"] * 4)

    async def racing_choose(
        candidates: list[CliproxyCandidate], **kwargs: Any
    ) -> tuple[routing.CliproxyDispatchChoice | None, object]:
        # Every request reads "no pin" before any writes, then each prefers another account.
        if kwargs.get("existing_account_id") is None and barrier.n_waiting < 6 and not barrier.broken:
            try:
                await asyncio.wait_for(barrier.wait(), timeout=2)
            except (asyncio.TimeoutError, asyncio.BrokenBarrierError):
                pass
            preferred = next(rotation)
            candidates = [item for item in candidates if item.auth_index == preferred] or candidates
        return await real_choose(candidates, **kwargs)

    monkeypatch.setattr(routing, "choose_cliproxy_route", racing_choose)
    choices = await asyncio.gather(*[_route(_chat(_conversation(1)), headers={"X-Session-Id": "s6"}) for _ in range(6)])
    accounts = {choice.account_id for choice in choices if choice is not None}
    assert len(accounts) == 1
    assert (await _pins())["cliproxy:session:s6"] in accounts


async def test_s6_claim_refuses_to_overwrite_a_live_foreign_pin(db_setup: bool) -> None:
    del db_setup
    async with get_background_session() as session:
        repo = routing._CliproxyStickyRepository(session)
        kind = StickySessionKind.STICKY_THREAD
        assert await repo.claim("k", "a", kind, expected_account_id=None, max_age_seconds=3600)
        assert not await repo.claim("k", "b", kind, expected_account_id=None, max_age_seconds=3600)
        assert await repo.claim("k", "b", kind, expected_account_id="a", max_age_seconds=3600)
        assert (await repo.lookup("k", kind=kind, max_age_seconds=3600))[0] == "b"
        await repo.release("k", kind, expected_account_id="a")
        assert (await repo.lookup("k", kind=kind, max_age_seconds=3600))[0] == "b"


async def test_s6_claim_takes_over_an_expired_pin(db_setup: bool) -> None:
    del db_setup
    kind = StickySessionKind.STICKY_THREAD
    async with get_background_session() as session:
        session.add(
            CliproxyStickySession(key="k", kind=kind.value, account_id="a", updated_at=utcnow() - timedelta(hours=2))
        )
        await session.commit()
        repo = routing._CliproxyStickyRepository(session)
        assert (await repo.lookup("k", kind=kind, max_age_seconds=3600))[0] is None
        assert await repo.claim("k", "b", kind, expected_account_id=None, max_age_seconds=3600)


# --- S11: purge expired pins -----------------------------------------------------


async def test_s11_purge_removes_only_expired_cliproxy_pins(db_setup: bool) -> None:
    del db_setup
    now = utcnow()
    async with get_background_session() as session:
        session.add_all(
            [
                CliproxyStickySession(
                    key="old", kind="prompt_cache", account_id="a", updated_at=now - timedelta(hours=3)
                ),
                CliproxyStickySession(key="new", kind="prompt_cache", account_id="a", updated_at=now),
            ]
        )
        await session.commit()
        deleted = await StickySessionsRepository(session).purge_cliproxy_before(now - timedelta(hours=1))
    assert deleted == 1
    assert set(await _pins()) == {"new"}


def test_s11_purge_and_lookup_share_one_lifetime() -> None:
    assert cliproxy_sticky_max_age_seconds(_settings()) == 3600
    settings = _settings(http_responses_session_bridge_prompt_cache_idle_ttl_seconds=600)
    assert cliproxy_sticky_max_age_seconds(settings) == 600
    assert routing._route_params(settings).max_age == 600
    fallback = _settings(http_responses_session_bridge_prompt_cache_idle_ttl_seconds=0)
    assert cliproxy_sticky_max_age_seconds(fallback) == 3600
