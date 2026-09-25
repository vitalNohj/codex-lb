from __future__ import annotations

import pytest

from app.modules.proxy.alias_pool_attempts import (
    DEFAULT_COOLDOWN_SECONDS,
    MAX_RETRY_AFTER_COOLDOWN_SECONDS,
    PAYMENT_REQUIRED_COOLDOWN_SECONDS,
    AliasPoolCooldownRegistry,
    ChatRequestAttribution,
    RetryableUpstreamFailure,
    is_retryable_upstream_status,
    retryable_failure_from_error,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.parametrize(
    ("status", "retryable"),
    [
        (401, True),
        (402, True),
        (403, True),
        (408, True),
        (429, True),
        (500, True),
        (502, True),
        (503, True),
        (504, True),
        (520, True),
        (526, True),
        (400, False),
        (404, False),
        (413, False),
        (422, False),
        (200, False),
        (527, False),
    ],
)
def test_retryable_classification_table(status: int, retryable: bool) -> None:
    assert is_retryable_upstream_status(status) is retryable
    failure = retryable_failure_from_error(status_code=status, message="x", headers=None)
    assert (failure is not None) is retryable


def test_402_cools_for_thirty_minutes() -> None:
    failure = retryable_failure_from_error(status_code=402, message="no credit", headers=None)
    assert failure is not None
    assert failure.cooldown_seconds() == PAYMENT_REQUIRED_COOLDOWN_SECONDS


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"Retry-After": "7"}, 7.0),
        ({"retry-after": "7"}, 7.0),
        ({"Retry-After": "0"}, 0.0),
        ({"Retry-After": "86400"}, MAX_RETRY_AFTER_COOLDOWN_SECONDS),
        ({"Retry-After": "not-a-date"}, DEFAULT_COOLDOWN_SECONDS),
        ({"Retry-After": "-5"}, DEFAULT_COOLDOWN_SECONDS),
        ({}, DEFAULT_COOLDOWN_SECONDS),
        (None, DEFAULT_COOLDOWN_SECONDS),
    ],
)
def test_429_cooldown_follows_retry_after_with_a_one_hour_cap(headers, expected: float) -> None:
    failure = retryable_failure_from_error(status_code=429, message="slow down", headers=headers)
    assert failure is not None
    assert failure.cooldown_seconds() == expected


def test_retry_after_is_ignored_for_non_429_statuses() -> None:
    failure = retryable_failure_from_error(status_code=503, message="busy", headers={"Retry-After": "3000"})
    assert failure is not None
    assert failure.retry_after_seconds is None
    assert failure.cooldown_seconds() == DEFAULT_COOLDOWN_SECONDS


def test_cooldown_entries_expire_lazily() -> None:
    clock = _Clock()
    registry = AliasPoolCooldownRegistry(clock=clock)
    registry.record_failure("a", RetryableUpstreamFailure(status_code=503, message="busy"))

    assert registry.health("a").state == "cooling"
    clock.advance(DEFAULT_COOLDOWN_SECONDS - 0.5)
    assert registry.health("a").state == "cooling"
    clock.advance(1.0)
    health = registry.health("a")
    assert health.state == "healthy"
    assert health.last_status is None


def test_success_clears_cooldown_immediately() -> None:
    clock = _Clock()
    registry = AliasPoolCooldownRegistry(clock=clock)
    registry.record_failure("a", RetryableUpstreamFailure(status_code=402, message="no credit"))
    registry.record_success("a")
    assert registry.cooldown_for("a") is None


def test_order_targets_keeps_ready_in_pool_order_and_sorts_cooling_soonest_first() -> None:
    clock = _Clock()
    registry = AliasPoolCooldownRegistry(clock=clock)
    registry.record_failure("a", RetryableUpstreamFailure(status_code=402, message="30 min"))
    registry.record_failure("c", RetryableUpstreamFailure(status_code=503, message="60 s"))

    ready, cooling = registry.order_targets(("a", "b", "c", "d"))

    assert ready == ("b", "d")
    assert cooling == ("c", "a")


def test_order_targets_breaks_ties_by_pool_order() -> None:
    clock = _Clock()
    registry = AliasPoolCooldownRegistry(clock=clock)
    registry.record_failure("b", RetryableUpstreamFailure(status_code=503, message="60 s"))
    registry.record_failure("a", RetryableUpstreamFailure(status_code=503, message="60 s"))

    ready, cooling = registry.order_targets(("a", "b"))

    assert ready == ()
    assert cooling == ("a", "b")


def test_cooldowns_are_keyed_by_target_not_provider() -> None:
    registry = AliasPoolCooldownRegistry(clock=_Clock())
    registry.record_failure("orcarouter/z-ai/glm-5.3", RetryableUpstreamFailure(status_code=402, message="x"))
    assert registry.health("orcarouter/auto").state == "healthy"


def test_retain_drops_entries_for_targets_no_longer_configured() -> None:
    registry = AliasPoolCooldownRegistry(clock=_Clock())
    registry.record_failure("a", RetryableUpstreamFailure(status_code=402, message="x"))
    registry.record_failure("b", RetryableUpstreamFailure(status_code=402, message="x"))
    registry.retain({"b"})
    assert registry.cooldown_for("a") is None
    assert registry.cooldown_for("b") is not None


def test_last_error_is_truncated() -> None:
    registry = AliasPoolCooldownRegistry(clock=_Clock())
    entry = registry.record_failure("a", RetryableUpstreamFailure(status_code=502, message="x" * 2000))
    assert len(entry.last_error) == 512


def test_attribution_direct_and_aliased_shapes() -> None:
    direct = ChatRequestAttribution.direct("orcarouter/auto")
    assert (direct.model, direct.upstream_model, direct.pool_attempts, direct.queue_ms) == (
        "orcarouter/auto",
        None,
        None,
        None,
    )
    aliased = ChatRequestAttribution.aliased(alias="custom_r1", target="cc/claude-opus-4-8")
    assert (aliased.model, aliased.upstream_model) == ("custom_r1", "cc/claude-opus-4-8")
    same = ChatRequestAttribution.aliased(alias="x", target="x")
    assert same.upstream_model is None
