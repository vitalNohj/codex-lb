"""The signal that a pinned Claude conversation stopped reading the prompt cache.

CLIProxyAPI's Claude OAuth requests carry a per-request hash in the first
system block that only ``api.anthropic.com`` strips before caching. Any hop
that rewrites the body makes every turn a full cache write. A turn served on
its conversation's existing pin with a cacheable prompt should read the cache,
so a sustained run of zero reads on those turns is what the alert watches.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from app.core.metrics import prometheus
from app.db.models import StickySessionKind
from app.modules.proxy import cliproxy_account_routing as routing
from app.modules.proxy.cliproxy_account_routing import (
    CLAUDE_CACHEABLE_PROMPT_TOKENS,
    CliproxyDispatchChoice,
    CliproxyRouteKind,
    record_claude_sticky_cache_result,
)

pytestmark = pytest.mark.unit


class _Counter:
    def __init__(self) -> None:
        self.values: dict[str, float] = {}
        self._result = ""

    def labels(self, *, result: str) -> _Counter:
        self._result = result
        return self

    def inc(self) -> None:
        self.values[self._result] = self.values.get(self._result, 0.0) + 1


@pytest.fixture(autouse=True)
def _counter(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Counter]:
    counter = _Counter()
    monkeypatch.setattr(routing, "cliproxy_claude_sticky_cache_total", counter)
    routing._CACHE_MISS_WARNED.clear()
    yield counter
    routing._CURRENT_CHOICE.set(None)
    routing._CACHE_MISS_WARNED.clear()


def _choose(
    *,
    route: CliproxyRouteKind = "sticky",
    model: str = "claude-sonnet-4-5",
    fallback: bool = False,
    account_id: str = "claude:a",
) -> None:
    routing._CURRENT_CHOICE.set(
        CliproxyDispatchChoice(
            account_id=account_id,
            provider="claude",
            auth_index="idx-a",
            prefix="acct-a",
            wire_model=f"acct-a/{model}",
            requested_model=model,
            route=route,
            sticky_key="pck-1",
            sticky_kind=StickySessionKind.PROMPT_CACHE,
            key_source="prompt_cache_key",
            fallback=fallback,
        )
    )


def test_the_metric_is_registered_when_prometheus_is_available() -> None:
    assert "cliproxy_claude_sticky_cache_total" in prometheus.__all__
    if prometheus.PROMETHEUS_AVAILABLE:
        assert prometheus.cliproxy_claude_sticky_cache_total is not None


def test_a_pinned_turn_with_a_cacheable_prompt_counts_hits_and_misses(_counter: _Counter) -> None:
    _choose()
    record_claude_sticky_cache_result(input_tokens=20_000, cached_input_tokens=19_000)
    record_claude_sticky_cache_result(input_tokens=20_000, cached_input_tokens=0)
    record_claude_sticky_cache_result(input_tokens=CLAUDE_CACHEABLE_PROMPT_TOKENS, cached_input_tokens=0)

    assert _counter.values == {"hit": 1, "miss": 2}


@pytest.mark.parametrize(
    "case",
    [
        # A new pin or a rebind lands on an account whose cache is cold: a
        # miss there is expected, not a fault.
        {"route": "selected"},
        {"route": "rebind"},
        # A fallback pin serves while the conversation's own pin cools down.
        {"fallback": True},
        # Other CLIProxyAPI families have no Anthropic cache to lose.
        {"model": "gemini-2.5-pro"},
    ],
)
def test_turns_that_may_miss_the_cache_are_not_counted(case: dict, _counter: _Counter) -> None:
    _choose(**case)
    record_claude_sticky_cache_result(input_tokens=20_000, cached_input_tokens=0)

    assert _counter.values == {}


def test_a_prompt_below_the_cacheable_minimum_is_not_counted(_counter: _Counter) -> None:
    _choose()
    record_claude_sticky_cache_result(input_tokens=CLAUDE_CACHEABLE_PROMPT_TOKENS - 1, cached_input_tokens=0)

    assert _counter.values == {}


def test_a_request_with_no_routed_credential_is_not_counted(_counter: _Counter) -> None:
    routing._CURRENT_CHOICE.set(None)
    record_claude_sticky_cache_result(input_tokens=20_000, cached_input_tokens=0)

    assert _counter.values == {}


def test_a_miss_warns_once_per_credential_within_the_window(
    caplog: pytest.LogCaptureFixture, _counter: _Counter
) -> None:
    caplog.set_level(logging.WARNING, logger=routing.logger.name)

    for _ in range(3):
        _choose(account_id="claude:a")
        record_claude_sticky_cache_result(input_tokens=20_000, cached_input_tokens=0)
    _choose(account_id="claude:b")
    record_claude_sticky_cache_result(input_tokens=20_000, cached_input_tokens=0)

    warnings = [r.getMessage() for r in caplog.records if "cliproxy_claude_sticky_cache_miss" in r.getMessage()]
    assert len(warnings) == 2
    assert "api.anthropic.com directly" in warnings[0]
    assert "input_tokens=20000" in warnings[0]
    assert _counter.values == {"miss": 4}


def test_a_hit_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger=routing.logger.name)
    _choose()
    record_claude_sticky_cache_result(input_tokens=20_000, cached_input_tokens=1)

    assert not [r for r in caplog.records if "cliproxy_claude_sticky_cache_miss" in r.getMessage()]
