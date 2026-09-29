from __future__ import annotations

import pytest

from app.core.clients.cliproxy_routing_config import (
    CliproxyRoutingConfigError,
    apply_session_affinity_yaml,
)

pytestmark = pytest.mark.unit

_CONFIG = """\
port: 8317
routing:
  strategy: "weighted-round-robin"
  # Same opening messages stay on one account. New chats still follow weight.
  session-affinity: true
  session-affinity-ttl: "1h"
  session-affinity-subagents: true
debug: true
"""


def test_turn_off_keeps_ttl_subagents_and_comments() -> None:
    updated = apply_session_affinity_yaml(_CONFIG, False)

    assert "session-affinity: false" in updated
    assert "session-affinity: true" not in updated
    assert 'session-affinity-ttl: "1h"' in updated
    assert "session-affinity-subagents: true" in updated
    assert "# Same opening messages stay on one account. New chats still follow weight." in updated
    assert "debug: true" in updated
    assert apply_session_affinity_yaml(updated, False) == updated


def test_turn_on_rewrites_only_the_flag_line() -> None:
    off = apply_session_affinity_yaml(_CONFIG, False)
    updated = apply_session_affinity_yaml(off, True)

    assert updated == _CONFIG


def test_missing_flag_stays_unchanged_when_turning_off() -> None:
    text = "routing:\n  strategy: round-robin\n  session-affinity-ttl: \"1h\"\n"
    assert apply_session_affinity_yaml(text, False) == text


def test_missing_flag_is_inserted_inside_the_routing_block() -> None:
    text = "routing:\n  strategy: round-robin\n  session-affinity-ttl: \"1h\"\ndebug: true\n"
    updated = apply_session_affinity_yaml(text, True)

    assert "session-affinity: true" in updated
    assert 'session-affinity-ttl: "1h"' in updated
    assert updated.index("session-affinity: true") < updated.index("debug: true")
    assert "session-affinity-ttl: true" not in updated


def test_commented_flag_is_not_treated_as_the_setting() -> None:
    text = "routing:\n  # session-affinity: false\n  strategy: round-robin\n"
    updated = apply_session_affinity_yaml(text, True)

    assert "# session-affinity: false" in updated
    assert "\n  session-affinity: true\n" in updated


def test_bare_routing_header_without_newline_stays_a_block() -> None:
    updated = apply_session_affinity_yaml("routing:", True)

    assert updated == "routing:\n  session-affinity: true\n"


def test_inline_routing_is_rejected() -> None:
    with pytest.raises(CliproxyRoutingConfigError):
        apply_session_affinity_yaml("routing: {strategy: round-robin}\n", True)


def test_nested_session_affinity_does_not_replace_the_routing_flag() -> None:
    text = "routing:\n  nested:\n    session-affinity: false\n  session-affinity: false\n"
    updated = apply_session_affinity_yaml(text, True)

    assert "\n    session-affinity: false\n" in updated
    assert "\n  session-affinity: true\n" in updated


def test_missing_direct_flag_is_inserted_when_only_a_nested_key_exists() -> None:
    text = "routing:\n  nested:\n    session-affinity: false\ndebug: true\n"
    updated = apply_session_affinity_yaml(text, True)

    assert "\n  session-affinity: true\n" in updated
    assert "\n    session-affinity: false\n" in updated
    assert updated.index("session-affinity: true") < updated.index("debug: true")
