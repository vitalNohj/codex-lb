from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.core.clients.proxy_websocket import UpstreamWebSocketTransportError
from app.core.config.settings import Settings
from app.modules.proxy import service as proxy_service
from app.modules.proxy._service.http_bridge import request_submit
from tests.simulation.virtual_time import VirtualClock
from tests.unit.test_http_bridge_idle_leases import _make_bridge_session

pytestmark = pytest.mark.unit
_MIXIN = request_submit._HTTPBridgeRequestSubmitMixin


def _request() -> proxy_service._WebSocketRequestState:
    return proxy_service._WebSocketRequestState(
        request_id="req_rotation",
        model="gpt-5.1",
        service_tier=None,
        reasoning_effort=None,
        api_key_reservation=None,
        started_at=4000,
        request_text=json.dumps({"type": "response.create", "model": "gpt-5.1", "input": "hello"}),
        event_queue=asyncio.Queue(),
        awaiting_response_created=True,
        response_create_sent_at=4000,
    )


def _service() -> SimpleNamespace:
    return SimpleNamespace(
        _clock=VirtualClock(monotonic_value=4000),
        _reconnect_http_bridge_session=AsyncMock(),
        _http_bridge_text_with_account_installation_id=lambda session, state, text: text,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("age, busy, rotates", [(3299, False, False), (3300, False, True), (3500, True, False)])
async def test_rotation_only_at_age_boundary_between_turns(monkeypatch, age, busy, rotates):
    monkeypatch.setattr(request_submit, "_service_get_settings", lambda: Settings(_env_file=None))
    session = _make_bridge_session()
    session.upstream_connected_at = 4000 - age
    request = _request()
    if busy:
        session.pending_requests.append(_request())
    service = _service()

    async with session.lifecycle_lock:
        await _MIXIN._rotate_idle_http_bridge_upstream(service, session, request_state=request)

    assert service._reconnect_http_bridge_session.await_count == int(rotates)
    if rotates:
        service._reconnect_http_bridge_session.assert_awaited_once_with(
            session, request_state=request, restart_reader=True, rotate_upstream=True
        )
    assert request.replay_count == 0


@pytest.mark.asyncio
async def test_rotation_honors_shorter_deployment_max_age(monkeypatch):
    monkeypatch.setattr(
        request_submit,
        "_service_get_settings",
        lambda: Settings(_env_file=None, http_responses_session_bridge_upstream_max_age_seconds=1200),
    )
    session = _make_bridge_session()
    session.upstream_connected_at = 2800
    service = _service()
    async with session.lifecycle_lock:
        await _MIXIN._rotate_idle_http_bridge_upstream(service, session, request_state=_request())
    service._reconnect_http_bridge_session.assert_awaited_once()


@pytest.mark.parametrize("max_age", [0, -1, 3600, 4000])
def test_rotation_max_age_stays_below_provider_limit(max_age):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, http_responses_session_bridge_upstream_max_age_seconds=max_age)


@pytest.mark.asyncio
async def test_explicit_rejection_retries_original_chain_once():
    session = _make_bridge_session()
    session.upstream.send_text = AsyncMock()
    request = _request()
    request.previous_response_id = "resp_previous"
    request.request_text = json.dumps({"type": "response.create", "previous_response_id": "resp_previous"})
    session.pending_requests.append(request)
    service = _service()

    assert await _MIXIN._retry_http_bridge_connection_limit_request(service, session)
    assert not await _MIXIN._retry_http_bridge_connection_limit_request(service, session)

    service._reconnect_http_bridge_session.assert_awaited_once_with(
        session, request_state=request, rotate_upstream=True
    )
    session.upstream.send_text.assert_awaited_once()
    assert json.loads(session.upstream.send_text.await_args.args[0])["previous_response_id"] == "resp_previous"
    assert request.previous_response_id == "resp_previous"
    # Existing not-found/full-resend recovery still has its own retry budget.
    assert request.replay_count == 0
    assert request.response_event_count == 0
    assert request.response_create_attempt_count == 1


@dataclass(frozen=True)
class _UnsafeRetry:
    field: str
    value: object


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        _UnsafeRetry("response_event_count", 1),
        _UnsafeRetry("response_id", "resp_created"),
        _UnsafeRetry("downstream_visible", True),
        _UnsafeRetry("upstream_model_output_seen", True),
        _UnsafeRetry("draining_until_terminal", True),
        _UnsafeRetry("event_queue", None),
        _UnsafeRetry("response_create_sent_at", None),
        _UnsafeRetry("request_text", None),
        _UnsafeRetry("upstream_connection_limit_retried", True),
    ],
    ids=lambda case: case.field,
)
async def test_connection_limit_never_replays_unsafe_turn(case):
    session = _make_bridge_session()
    request = _request()
    setattr(request, case.field, case.value)
    session.pending_requests.append(request)
    service = _service()

    assert not await _MIXIN._retry_http_bridge_connection_limit_request(service, session)
    service._reconnect_http_bridge_session.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("pending_count", [0, 2])
async def test_connection_limit_does_not_replay_multiplexed_turns(pending_count):
    session = _make_bridge_session()
    session.pending_requests.extend(_request() for _ in range(pending_count))
    service = _service()
    assert not await _MIXIN._retry_http_bridge_connection_limit_request(service, session)
    service._reconnect_http_bridge_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_replacement_send_transport_failure_is_not_retried():
    session = _make_bridge_session()
    failure = UpstreamWebSocketTransportError("transport failed", error_code="upstream_unavailable")
    session.upstream.send_text = AsyncMock(side_effect=failure)
    request = _request()
    session.pending_requests.append(request)
    service = _service()

    with pytest.raises(UpstreamWebSocketTransportError):
        await _MIXIN._retry_http_bridge_connection_limit_request(service, session)
    assert request.upstream_connection_limit_retried
    assert not await _MIXIN._retry_http_bridge_connection_limit_request(service, session)
    assert service._reconnect_http_bridge_session.await_count == 1
