from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.core.clients.claude_sidecar import SidecarModel
from app.core.clients.openrouter_sidecar import OpenRouterSidecarError, OpenRouterSidecarUnavailableError
from app.db.models import FreeModelProbeState
from app.modules.free_model_discovery.candidates import (
    build_candidates,
    classify_group,
    is_free_model_id,
    is_router_selector,
    split_candidates,
)
from app.modules.free_model_discovery.pacing import ProviderPacer, cooldown_for_failure_streak
from app.modules.free_model_discovery.probe import build_probe_payload, classify_completion, probe_model

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 11, 12, 0, 0)


# --- candidates ------------------------------------------------------------


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("deepseek/deepseek-r1:free", True),
        ("openrouter/free", True),
        ("orcarouter/free", True),
        ("deepseek/deepseek-v4-flash-free", True),
        ("z-ai/glm-5.3-flash", False),
        ("deepseek/deepseek-v4.1-flash", False),
        ("FREEDOM/model", True),
    ],
)
def test_is_free_model_id_is_a_substring_match(model_id: str, expected: bool) -> None:
    assert is_free_model_id(model_id) is expected


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("orcarouter/free", True),
        ("openrouter/free", True),
        ("deepseek/deepseek-v4-flash-free", False),
        ("deepseek/deepseek-r1:free", False),
        ("free", True),
    ],
)
def test_is_router_selector_matches_only_a_bare_free_last_segment(model_id: str, expected: bool) -> None:
    assert is_router_selector(model_id) is expected


def test_split_candidates_filters_pinned_selectors_and_paid() -> None:
    models = [
        SidecarModel(id="deepseek/deepseek-r1:free"),
        SidecarModel(id="orcarouter/free"),
        SidecarModel(id="z-ai/glm-5.3-flash"),
        SidecarModel(id="Deepseek/Deepseek-V4-Flash-Free"),
        SidecarModel(id="deepseek/deepseek-v4-flash-free"),
        SidecarModel(id="qwen/qwen3-coder:free"),
    ]
    split = split_candidates(models, pinned_keys={"qwen/qwen3-coder:free"})
    assert [model.id for model in split.candidates] == [
        "deepseek/deepseek-r1:free",
        "Deepseek/Deepseek-V4-Flash-Free",
    ]
    assert split.discovered_count == 6
    assert split.free_count == 5
    assert split.already_pinned_count == 1
    assert split.skipped_selector_count == 1


def _state(*, verdict: str, cooldown_until: datetime | None, streak: int = 1) -> FreeModelProbeState:
    return FreeModelProbeState(
        provider="openrouter",
        model_id="x",
        last_verdict=verdict,
        last_verdict_at=_NOW - timedelta(hours=2),
        failure_streak=streak,
        cooldown_until=cooldown_until,
    )


def test_classify_group_precedence() -> None:
    assert classify_group(state=None, unresolved_last_run=False, now=_NOW) == "new"
    assert classify_group(state=None, unresolved_last_run=True, now=_NOW) == "unresolved"
    in_cooldown = _state(verdict="failed", cooldown_until=_NOW + timedelta(hours=1))
    assert classify_group(state=in_cooldown, unresolved_last_run=True, now=_NOW) == "cooldown"
    past_cooldown = _state(verdict="failed", cooldown_until=_NOW - timedelta(minutes=1))
    assert classify_group(state=past_cooldown, unresolved_last_run=False, now=_NOW) == "due"
    passed_unpinned = _state(verdict="passed", cooldown_until=None, streak=0)
    assert classify_group(state=passed_unpinned, unresolved_last_run=False, now=_NOW) == "due"


def test_build_candidates_carries_state_memory() -> None:
    state = _state(verdict="failed", cooldown_until=_NOW + timedelta(hours=5), streak=2)
    candidates = build_candidates(
        provider="openrouter",
        models=[SidecarModel(id="a/b:free", owned_by="a"), SidecarModel(id="c/d:free")],
        states={"a/b:free": state},
        unresolved_keys={"c/d:free"},
        now=_NOW,
    )
    assert [(c.model_id, c.group) for c in candidates] == [("a/b:free", "cooldown"), ("c/d:free", "unresolved")]
    assert candidates[0].failure_streak == 2
    assert candidates[0].last_verdict == "failed"
    assert candidates[0].owned_by == "a"
    assert candidates[1].last_verdict is None


# --- probe -----------------------------------------------------------------


def test_probe_payload_is_non_streaming_and_bounded() -> None:
    payload = build_probe_payload("a/b:free")
    assert payload["model"] == "a/b:free"
    assert payload["stream"] is False
    assert payload["max_tokens"] == 16


def test_classify_completion_passes_on_non_empty_content_and_records_diagnostics() -> None:
    result = classify_completion(
        {"choices": [{"message": {"role": "assistant", "content": " Sure, OK! ", "reasoning": "thinking hard"}}]}
    )
    assert result.verdict == "passed"
    assert result.http_status == 200
    assert result.content_chars == len("Sure, OK!")
    assert result.content_ok_match is True
    assert result.reasoning_chars == len("thinking hard")


def test_classify_completion_two_character_ok_passes() -> None:
    result = classify_completion({"choices": [{"message": {"content": "ok"}}]})
    assert result.verdict == "passed"
    assert result.content_ok_match is True


def test_classify_completion_content_parts_list_is_joined() -> None:
    result = classify_completion({"choices": [{"message": {"content": [{"type": "text", "text": "o"}, "k"]}}]})
    assert result.verdict == "passed"
    assert result.content_chars == 2


def test_classify_completion_fails_only_on_well_formed_empty_content() -> None:
    result = classify_completion({"choices": [{"message": {"content": "   ", "reasoning_content": ""}}]})
    assert result.verdict == "failed"
    assert result.content_chars == 0
    assert result.reasoning_chars == 0
    assert classify_completion({"choices": [{"message": {"content": None}}]}).verdict == "failed"


@pytest.mark.parametrize(
    "body",
    [
        [],
        "plain",
        {},
        {"choices": []},
        {"choices": [None]},
        {"choices": [{"message": "no"}]},
        {"choices": [{"message": {"content": 42}}]},
        {"error": {"message": "rate limited"}, "choices": []},
    ],
)
def test_classify_completion_malformed_200_is_inconclusive(body) -> None:
    result = classify_completion(body)
    assert result.verdict == "inconclusive"
    assert result.http_status == 200


def test_classify_completion_reports_error_message_when_choices_missing() -> None:
    result = classify_completion({"error": {"message": "rate limited"}})
    assert result.verdict == "inconclusive"
    assert "rate limited" in result.outcome


class _Client:
    def __init__(self, outcome) -> None:
        self._outcome = outcome
        self.payloads = []

    async def chat_completion(self, payload):
        self.payloads.append(dict(payload))
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


@pytest.mark.asyncio
async def test_probe_model_transport_error_is_inconclusive_without_status() -> None:
    result = await probe_model(_Client(OpenRouterSidecarUnavailableError("connection reset")), "a/b:free")
    assert result.verdict == "inconclusive"
    assert result.http_status is None
    assert result.rate_limited is False
    assert "connection reset" in result.outcome


@pytest.mark.asyncio
async def test_probe_model_429_is_inconclusive_and_carries_retry_hint() -> None:
    error = OpenRouterSidecarError(429, "slow down", body={"error": {"message": "slow down", "retry_after": "30"}})
    result = await probe_model(_Client(error), "a/b:free")
    assert result.verdict == "inconclusive"
    assert result.http_status == 429
    assert result.rate_limited is True
    assert result.retry_after_seconds == 30.0


@pytest.mark.asyncio
async def test_probe_model_404_is_inconclusive_not_failed() -> None:
    result = await probe_model(_Client(OpenRouterSidecarError(404, "no providers")), "a/b:free")
    assert result.verdict == "inconclusive"
    assert result.http_status == 404


@pytest.mark.asyncio
async def test_probe_model_clean_200_passes() -> None:
    client = _Client({"choices": [{"message": {"content": "ok"}}]})
    result = await probe_model(client, "a/b:free")
    assert result.verdict == "passed"
    assert client.payloads[0]["model"] == "a/b:free"


# --- pacing ----------------------------------------------------------------


def test_cooldown_schedule_escalates_and_saturates() -> None:
    assert cooldown_for_failure_streak(0) == timedelta(hours=1)
    assert cooldown_for_failure_streak(1) == timedelta(hours=1)
    assert cooldown_for_failure_streak(2) == timedelta(hours=6)
    assert cooldown_for_failure_streak(3) == timedelta(days=1)
    assert cooldown_for_failure_streak(4) == timedelta(days=3)
    assert cooldown_for_failure_streak(5) == timedelta(days=7)
    assert cooldown_for_failure_streak(50) == timedelta(days=7)


def test_pacer_starts_at_floor_and_validates() -> None:
    pacer = ProviderPacer(floor_seconds=20, cap_seconds=600)
    assert pacer.current_seconds == 20
    with pytest.raises(ValueError):
        ProviderPacer(floor_seconds=0, cap_seconds=10)
    with pytest.raises(ValueError):
        ProviderPacer(floor_seconds=30, cap_seconds=10)


def test_pacer_doubles_on_429_up_to_cap_and_honours_retry_after() -> None:
    pacer = ProviderPacer(floor_seconds=20, cap_seconds=100)
    assert pacer.on_rate_limited(None) == 40
    assert pacer.on_rate_limited(None) == 80
    assert pacer.on_rate_limited(None) == 100
    assert pacer.on_rate_limited(5) == 20  # below floor clamps to floor
    assert pacer.on_rate_limited(70) == 70
    assert pacer.on_rate_limited(10_000) == 100


def test_pacer_decays_after_clean_streak_and_holds_on_inconclusive() -> None:
    pacer = ProviderPacer(floor_seconds=20, cap_seconds=600)
    pacer.on_rate_limited(None)
    pacer.on_rate_limited(None)
    assert pacer.current_seconds == 80
    assert pacer.on_inconclusive() == 80
    assert pacer.on_verdict() == 80
    assert pacer.on_verdict() == 80
    assert pacer.on_verdict() == 40
    assert pacer.on_verdict() == 40
    assert pacer.on_inconclusive() == 40  # resets the clean streak
    assert pacer.on_verdict() == 40
    assert pacer.on_verdict() == 40
    assert pacer.on_verdict() == 20
    assert pacer.on_verdict() == 20
    assert pacer.on_verdict() == 20
    assert pacer.on_verdict() == 20  # never below floor


@pytest.mark.asyncio
async def test_probe_redacts_the_configured_credential_from_upstream_error_text():
    """Upstream error text is persisted to ``last_outcome`` and shown in the
    dashboard, so a provider that echoes the Authorization header must not
    leak the key there. Uses a synthetic sentinel credential."""

    from app.core.clients.orcarouter_sidecar import OrcaRouterSidecarError
    from app.modules.free_model_discovery.probe import probe_model

    sentinel = "sk-orca-TESTSENTINEL0123456789"

    class _EchoingClient:
        async def chat_completion(self, payload):
            raise OrcaRouterSidecarError(401, f"rejected token {sentinel} for Bearer {sentinel}")

    result = await probe_model(_EchoingClient(), "a/b:free", api_key=sentinel)

    assert sentinel not in result.outcome
    assert "[redacted]" in result.outcome
    # The diagnostic is still useful: status and shape survive redaction.
    assert result.http_status == 401
    assert result.verdict == "inconclusive"


def test_plan_sanitizer_redacts_the_token_not_just_the_bearer_prefix():
    """``_sanitize`` used to insert ``[redacted]`` *after* ``"Bearer "`` and
    leave the token itself intact, so it redacted nothing."""

    from app.modules.free_model_discovery.service import _sanitize

    sentinel = "sk-orca-TESTSENTINEL0123456789"

    sanitized = _sanitize(f"Bearer {sentinel} was rejected", api_key=sentinel)

    assert sentinel not in sanitized
    assert "[redacted]" in sanitized


@pytest.mark.asyncio
async def test_gather_owned_cancels_siblings_before_returning_the_error():
    """A provider error must not leave its sibling probing.

    The bare ``gather`` this replaced propagated the first exception while
    siblings kept running; the driver's caller then released the leader lock,
    so detached tasks kept hitting providers while the next tick could start a
    second driver. Ownership must end with no task still running.

    NOT EXECUTED in the pass that added it.
    """

    import asyncio

    from app.modules.free_model_discovery.runner import _gather_owned

    started = asyncio.Event()
    sibling_cleanup_ran = asyncio.Event()

    async def _failing() -> None:
        await started.wait()
        raise RuntimeError("provider exploded")

    async def _long_sibling() -> None:
        started.set()
        try:
            await asyncio.sleep(3600)  # a real run paces for hours
        except asyncio.CancelledError:
            sibling_cleanup_ran.set()
            raise

    tasks = [asyncio.create_task(_failing()), asyncio.create_task(_long_sibling())]

    with pytest.raises(RuntimeError, match="provider exploded"):
        await _gather_owned(tasks)

    # The original error still propagates, AND nothing is left behind.
    assert all(task.done() for task in tasks)
    assert sibling_cleanup_ran.is_set()


@pytest.mark.asyncio
async def test_gather_owned_cancels_siblings_when_the_parent_is_cancelled():
    """Shutdown cancels the driver; its provider tasks must not outlive it.

    NOT EXECUTED in the pass that added it.
    """

    import asyncio

    from app.modules.free_model_discovery.runner import _gather_owned

    both_started = asyncio.Event()
    cleanups: list[str] = []

    async def _worker(name: str) -> None:
        if name == "b":
            both_started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cleanups.append(name)
            raise

    tasks = [asyncio.create_task(_worker("a")), asyncio.create_task(_worker("b"))]
    parent = asyncio.create_task(_gather_owned(tasks))
    await both_started.wait()

    parent.cancel()
    with pytest.raises(asyncio.CancelledError):
        await parent

    # Cancellation propagated to every sibling and each ran its cleanup before
    # ownership was released.
    assert all(task.done() for task in tasks)
    assert sorted(cleanups) == ["a", "b"]
