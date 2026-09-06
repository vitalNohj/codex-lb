"""Terminal HTTP-bridge failures must surface the upstream error, not a laundered 502.

When the pre-created retry path exhausts, it has already captured the real
upstream error on the request state (``error_code_override`` and friends, set by
``_http_bridge_precreated_retry_failure_error``). The terminal-event builder used
by the retry-exhaustion branch previously discarded those overrides and emitted a
hardcoded ``stream_incomplete``, which ``_status_for_error`` then maps to 502.

A quota rejection therefore reached the codex CLI as a transport fault, which it
retried five times before printing its canned "high demand" message instead of
reporting the usage limit.
"""

from __future__ import annotations

from app.core.openai.models import OpenAIError
from app.modules.proxy import api as proxy_api
from app.modules.proxy import service as proxy_service
from app.modules.proxy._service.http_bridge import upstream_events as http_bridge_upstream_events

_USAGE_LIMIT_MESSAGE = "Rate limit exceeded. Try again in 300s"


def _request_state_with_retry_failure_overrides(
    *,
    error_code: str,
    error_message: str,
    error_type: str,
    http_status: int,
) -> proxy_service._WebSocketRequestState:
    """Build the request state exactly as the retry path leaves it on exhaustion.

    Mirrors the assignment in
    ``app/modules/proxy/_service/http_bridge/request_submit.py`` where
    ``_http_bridge_precreated_retry_failure_error(exc)`` is unpacked onto the
    request state.
    """
    request_state = proxy_service._WebSocketRequestState(
        request_id="req_usage_limit",
        model="gpt-5.6-sol",
        service_tier=None,
        reasoning_effort=None,
        api_key_reservation=None,
        started_at=0.0,
    )
    request_state.error_http_status_override = http_status
    request_state.error_code_override = error_code
    request_state.error_message_override = error_message
    request_state.error_type_override = error_type
    return request_state


def _terminal_error_from_state(
    request_state: proxy_service._WebSocketRequestState,
) -> tuple[str, str, str, int]:
    """Run the real terminal-event builder and the real downstream status mapper."""
    _downstream_text, _event_block, _event, payload, event_type = (
        proxy_service._build_stream_incomplete_terminal_event_for_request(request_state)
    )
    assert event_type == "response.failed"
    assert payload is not None
    response = payload["response"]
    assert isinstance(response, dict)
    error = response["error"]
    assert isinstance(error, dict)
    code = error["code"]
    message = error["message"]
    error_type = error["type"]
    assert isinstance(code, str)
    assert isinstance(message, str)
    assert isinstance(error_type, str)
    status = proxy_api._status_for_error(OpenAIError(code=code, message=message, type=error_type))
    return code, message, error_type, status


def test_retry_exhaustion_surfaces_upstream_usage_limit_as_429() -> None:
    request_state = _request_state_with_retry_failure_overrides(
        error_code="usage_limit_reached",
        error_message=_USAGE_LIMIT_MESSAGE,
        error_type="usage_limit_reached",
        http_status=429,
    )

    code, message, error_type, status = _terminal_error_from_state(request_state)

    assert code == "usage_limit_reached"
    assert code != "stream_incomplete"
    assert message == _USAGE_LIMIT_MESSAGE
    assert error_type == "usage_limit_reached"
    assert status == 429
    assert status != 502


def test_retry_exhaustion_keeps_captured_http_status_override() -> None:
    """The retry path's captured status must not be clobbered back to 502."""
    request_state = _request_state_with_retry_failure_overrides(
        error_code="usage_limit_reached",
        error_message=_USAGE_LIMIT_MESSAGE,
        error_type="usage_limit_reached",
        http_status=429,
    )

    http_bridge_upstream_events._apply_http_bridge_terminal_error_status(request_state)

    assert request_state.error_http_status_override == 429


def test_terminal_status_is_derived_from_captured_code_when_status_missing() -> None:
    """A capture site that recorded only a code must not get a contradicting 502.

    The emitted event carries the captured code, so forcing 502 here would
    reintroduce the exact laundering (429-class body behind a 502 status).
    """
    request_state = _request_state_with_retry_failure_overrides(
        error_code="usage_limit_reached",
        error_message=_USAGE_LIMIT_MESSAGE,
        error_type="usage_limit_reached",
        http_status=429,
    )
    request_state.error_http_status_override = None

    http_bridge_upstream_events._apply_http_bridge_terminal_error_status(request_state)
    code, _message, _error_type, status = _terminal_error_from_state(request_state)

    assert code == "usage_limit_reached"
    assert status == 429
    assert request_state.error_http_status_override == status


def test_terminal_status_matches_emitted_code_for_selection_failure() -> None:
    """A genuine selection failure keeps its own 503, not a re-labelled 429/502."""
    request_state = _request_state_with_retry_failure_overrides(
        error_code="no_accounts",
        error_message="No active accounts available",
        error_type="server_error",
        http_status=503,
    )
    request_state.error_http_status_override = None

    http_bridge_upstream_events._apply_http_bridge_terminal_error_status(request_state)
    code, _message, _error_type, status = _terminal_error_from_state(request_state)

    assert code == "no_accounts"
    assert status == 503
    assert request_state.error_http_status_override == status


def test_retry_exhaustion_without_overrides_still_reports_stream_incomplete() -> None:
    """Transport failures that captured no specific code keep the 502 default."""
    request_state = proxy_service._WebSocketRequestState(
        request_id="req_transport_drop",
        model="gpt-5.6-sol",
        service_tier=None,
        reasoning_effort=None,
        api_key_reservation=None,
        started_at=0.0,
    )

    http_bridge_upstream_events._apply_http_bridge_terminal_error_status(request_state)

    code, _message, _error_type, status = _terminal_error_from_state(request_state)

    assert code == "stream_incomplete"
    assert status == 502
    assert request_state.error_http_status_override == 502
