from __future__ import annotations

import pytest

from app.core.conversation.opencode_go_session import (
    OPENCODE_SESSION_HEADER,
    apply_opencode_go_session_header,
    resolve_opencode_go_session_id,
)

pytestmark = pytest.mark.unit


def test_direct_client_session_header_is_forwarded_verbatim() -> None:
    # A client already speaking Go's protocol owns its session id. Rewriting it
    # would split one conversation across two upstream prompt-cache keys.
    resolved = resolve_opencode_go_session_id(
        {"user-agent": "opencode/1.2.3", OPENCODE_SESSION_HEADER: "  ses_abc123  "}
    )

    assert resolved == "ses_abc123"


def test_direct_header_wins_over_derivable_fallback() -> None:
    resolved = resolve_opencode_go_session_id(
        {
            "user-agent": "opencode/1.2.3",
            OPENCODE_SESSION_HEADER: "direct-value",
            "x-session-id": "fallback-value",
        }
    )

    assert resolved == "direct-value"


def test_blank_direct_header_falls_through_rather_than_forwarding_empty() -> None:
    resolved = resolve_opencode_go_session_id(
        {"user-agent": "opencode/1.2.3", OPENCODE_SESSION_HEADER: "   ", "x-session-id": "conv-1"}
    )

    assert resolved is not None
    assert resolved.startswith("ses_")


def test_over_long_direct_header_is_hashed_rather_than_forwarded_or_dropped() -> None:
    # Forwarding unbounded would let a client push arbitrary bytes upstream and
    # truncating would invent an identifier the client never used - but the
    # value is still a real conversation, so it is hashed to a bounded opaque
    # id that stays stable across turns rather than discarded.
    long_value = "x" * 500
    resolved = resolve_opencode_go_session_id(
        {"user-agent": "opencode/1.2.3", OPENCODE_SESSION_HEADER: long_value}
    )

    assert resolved is not None
    assert resolved.startswith("ses_")
    assert len(resolved) == len("ses_") + 32
    assert resolved == resolve_opencode_go_session_id(
        {"user-agent": "opencode/1.2.3", OPENCODE_SESSION_HEADER: long_value}
    )


@pytest.mark.parametrize(
    "header_name",
    ["x-parent-session-id", "x-session-id", "x-session-affinity"],
)
def test_opencode_fallback_headers_derive_an_opaque_id(header_name: str) -> None:
    # An OpenCode client pointed at codex-lb under a non-``opencode`` provider id
    # sends these instead, carrying the same underlying session value.
    resolved = resolve_opencode_go_session_id({"user-agent": "opencode/1.2.3", header_name: "conversation-7"})

    assert resolved is not None
    assert resolved.startswith("ses_")
    assert len(resolved) == len("ses_") + 32
    # The raw client identifier never leaves the process.
    assert "conversation-7" not in resolved


def test_codex_thread_id_derives_an_id() -> None:
    resolved = resolve_opencode_go_session_id({"user-agent": "codex_cli_rs/1.0", "thread-id": "thread-9"})

    assert resolved is not None
    assert resolved.startswith("ses_")
    assert "thread-9" not in resolved


def test_same_conversation_is_stable_across_turns() -> None:
    headers = {"user-agent": "opencode/1.2.3", "x-session-id": "conv-42"}

    first = resolve_opencode_go_session_id(dict(headers))
    second = resolve_opencode_go_session_id(dict(headers))

    # Stability is the whole point: Go uses this value for prompt-cache
    # affinity, so a value that changed per request would be worse than none.
    assert first == second


def test_different_conversations_differ() -> None:
    a = resolve_opencode_go_session_id({"user-agent": "opencode/1.2.3", "x-session-id": "conv-a"})
    b = resolve_opencode_go_session_id({"user-agent": "opencode/1.2.3", "x-session-id": "conv-b"})

    assert a != b


def test_same_raw_id_from_different_agents_stays_isolated() -> None:
    opencode = resolve_opencode_go_session_id({"user-agent": "opencode/1.0", "x-session-id": "shared-id"})
    codex = resolve_opencode_go_session_id({"user-agent": "codex_cli_rs/1.0", "thread-id": "shared-id"})

    # Agent namespacing is what stops two clients that happen to reuse the same
    # raw id from silently sharing one upstream conversation's cache.
    assert opencode != codex


def test_unknown_client_yields_no_header() -> None:
    # Honest documented outcome: unknown identity means no affinity, not a
    # fabricated per-request id that forfeits affinity while looking correct.
    assert resolve_opencode_go_session_id({"user-agent": "curl/8.4.0", "x-session-id": "conv-1"}) is None
    assert resolve_opencode_go_session_id({}) is None
    assert resolve_opencode_go_session_id({"user-agent": "opencode/1.0"}) is None


def test_header_names_are_case_insensitive() -> None:
    resolved = resolve_opencode_go_session_id({"User-Agent": "OpenCode/2.0", "X-Opencode-Session": "ses_mixed"})

    assert resolved == "ses_mixed"


def test_apply_sets_header_without_mutating_input() -> None:
    base = {"Authorization": "Bearer sk-go-key", "User-Agent": "codex-lb/1.0"}

    result = apply_opencode_go_session_header(base, {"user-agent": "opencode/1.0", "x-session-id": "conv-1"})

    assert OPENCODE_SESSION_HEADER in result
    assert OPENCODE_SESSION_HEADER not in base
    assert result["Authorization"] == "Bearer sk-go-key"


def test_apply_never_lets_client_headers_reach_authorization_or_host() -> None:
    base = {"Authorization": "Bearer sk-go-real", "User-Agent": "codex-lb/1.0"}

    result = apply_opencode_go_session_header(
        base,
        {
            "user-agent": "opencode/1.0",
            "x-session-id": "conv-1",
            "authorization": "Bearer attacker",
            "host": "evil.example.com",
            "cookie": "secret",
        },
    )

    assert result["Authorization"] == "Bearer sk-go-real"
    assert "host" not in {key.lower() for key in result}
    assert "cookie" not in {key.lower() for key in result}
    # Exactly one header may be added by this path.
    assert set(result) - set(base) == {OPENCODE_SESSION_HEADER}


def test_apply_with_no_client_headers_is_a_passthrough() -> None:
    base = {"Authorization": "Bearer sk-go-key"}

    assert apply_opencode_go_session_header(base, None) == base


def test_resolution_never_raises_on_hostile_input() -> None:
    class _Explosive:
        def items(self):
            raise RuntimeError("boom")

    # Session derivation must never be able to fail a request.
    assert resolve_opencode_go_session_id(_Explosive()) is None  # type: ignore[arg-type]
