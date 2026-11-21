from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any

from app.modules.proxy._service.http_bridge.helpers import _http_bridge_reconnect_selection_failure
from app.modules.proxy._service.http_bridge.request_submit import _http_bridge_owner_free_full_resend_text
from app.modules.proxy.replay_safety import project_responses_payload_for_account_neutral_replay

_USER = {"role": "user", "content": [{"type": "input_text", "text": "first question"}]}
_REASONING = {
    "type": "reasoning",
    "id": "rs_owner_1",
    "summary": [],
    "encrypted_content": "gAAAA-owner-encrypted-reasoning",
}
_ASSISTANT = {
    "type": "message",
    "id": "msg_owner_1",
    "role": "assistant",
    "content": [{"type": "output_text", "text": "OK"}],
}
_FOLLOW_UP = {"role": "user", "content": [{"type": "input_text", "text": "second question"}]}


def _full_resend(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": "gpt-5.1",
        "instructions": "Return exactly OK.",
        "input": [_USER, _REASONING, _ASSISTANT, _FOLLOW_UP],
        "store": False,
        "stream": True,
        "include": ["reasoning.encrypted_content"],
        "reasoning": {"effort": "high", "summary": "auto"},
    }
    payload.update(overrides)
    return payload


def test_full_resend_projection_drops_only_owner_reasoning_and_item_ids() -> None:
    projected = project_responses_payload_for_account_neutral_replay(_full_resend())

    assert projected is not None
    assert projected["input"] == [
        _USER,
        {key: value for key, value in _ASSISTANT.items() if key != "id"},
        _FOLLOW_UP,
    ]
    assert projected["instructions"] == "Return exactly OK."


def test_full_resend_projection_refuses_anchored_requests() -> None:
    assert project_responses_payload_for_account_neutral_replay(_full_resend(previous_response_id="resp_1")) is None
    assert project_responses_payload_for_account_neutral_replay(_full_resend(conversation="conv_1")) is None


def test_full_resend_projection_refuses_account_scoped_files() -> None:
    file_message = {"role": "user", "content": [{"type": "input_file", "file_id": "file-owner"}]}
    payload = _full_resend(input=[_USER, _ASSISTANT, file_message])

    assert project_responses_payload_for_account_neutral_replay(payload) is None


def test_full_resend_projection_refuses_input_without_a_user_turn() -> None:
    assert project_responses_payload_for_account_neutral_replay(_full_resend(input=[_REASONING])) is None


def test_owner_free_full_resend_text_keeps_the_response_create_frame() -> None:
    text = json.dumps({"type": "response.create", **_full_resend()})

    projected_text = _http_bridge_owner_free_full_resend_text(text)

    assert projected_text is not None
    projected = json.loads(projected_text)
    assert projected["type"] == "response.create"
    assert [item.get("type") for item in projected["input"]] == [None, "message", None]


def test_required_owner_at_usage_limit_gets_short_retry_without_its_reset() -> None:
    resets_at = int(time.time()) + 3_000
    selection = SimpleNamespace(
        account=None,
        error_code="usage_limit_reached",
        error_message="Rate limit exceeded. Try again in 3000s",
        resets_at=resets_at,
        owner_hold_expired=False,
    )

    error = _http_bridge_reconnect_selection_failure(selection, "acc-owner")

    assert error.status_code == 503
    assert error.payload["error"]["code"] == "previous_response_owner_unavailable"
    assert "resets_at" not in error.payload["error"]
    assert "without previous_response_id" in error.payload["error"]["message"]
    assert error.retry_after_seconds == 3


def test_required_owner_rate_limited_without_reset_still_gets_retryable_503() -> None:
    selection = SimpleNamespace(
        account=None,
        error_code=None,
        error_message="Rate limit exceeded. Try again in 0s",
        resets_at=None,
        owner_hold_expired=False,
    )

    error = _http_bridge_reconnect_selection_failure(selection, "acc-owner")

    assert error.status_code == 503
    assert error.retry_after_seconds is not None and error.retry_after_seconds > 0


def test_required_owner_paused_keeps_the_owner_unavailable_502() -> None:
    selection = SimpleNamespace(
        account=None,
        error_code=None,
        error_message="All accounts are paused",
        resets_at=None,
        owner_hold_expired=False,
    )

    error = _http_bridge_reconnect_selection_failure(selection, "acc-owner")

    assert error.status_code == 502
    assert error.payload["error"]["code"] == "previous_response_owner_unavailable"
