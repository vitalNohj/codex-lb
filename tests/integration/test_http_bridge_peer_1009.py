"""The Responses bridge distinguishes peer rejection from a local size limit."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from app.core.clients.proxy_websocket import WebsocketsUpstreamWebSocket
from app.core.utils.sse import parse_sse_data_json
from app.dependencies import get_proxy_service_for_app
from app.modules.proxy import service as proxy_module
from app.modules.proxy._service import support as proxy_support
from app.modules.proxy._service.http_bridge import streaming as bridge_streaming
from app.modules.proxy.load_balancer import AccountSelection
from tests.integration.test_http_responses_bridge import (
    _cleanup_http_bridge_sessions,  # noqa: F401
    _get_account,
    _import_account,
    _install_proxy_settings,
    _make_app_settings,
    _make_dashboard_settings,
    _promotion_history,
    _PromotionUpstreamWebSocket,
    _SilentUpstreamWebSocket,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("phase", "peer_first", "status", "code"),
    [
        ("send", True, 400, "payload_too_large"),
        ("send", False, 502, "upstream_unavailable"),
        ("idle-retry-send", True, 400, "payload_too_large"),
        ("receive", True, 400, "payload_too_large"),
        ("receive", False, 502, "stream_incomplete"),
        ("streaming", True, 200, "payload_too_large"),
    ],
)
async def test_bridge_size_close_is_terminal(async_client, app_instance, monkeypatch, phase, peer_first, status, code):
    dashboard = _make_dashboard_settings()
    dashboard.http_downstream_transport_policy = "smart"
    app_settings = _make_app_settings(enabled=True)
    first_upstreams = []
    if phase == "idle-retry-send":
        dashboard.http_downstream_transport_policy = "always_websocket"
        app_settings.sse_keepalive_interval_seconds = 0.01
        monkeypatch.setattr(proxy_module, "_HTTP_BRIDGE_STARTUP_KEEPALIVE_GRACE_SECONDS", 0.01)
        monkeypatch.setattr(bridge_streaming, "_http_bridge_eventless_max_keepalive_count", lambda *a, **kw: 1)
        first_upstreams.append(_SilentUpstreamWebSocket())
    _install_proxy_settings(monkeypatch, app_settings=app_settings, dashboard_settings=dashboard)
    account_id = await _import_account(async_client, "acc_peer_size", "peer-size@example.com")
    account = await _get_account(account_id)
    penalty = AsyncMock()
    close = Close(1009, "message too big")
    rejection = ConnectionClosedError(close, close, peer_first)
    dispatched = asyncio.Event()
    messages = iter(
        [
            '{"type":"response.created","response":{"id":"resp_size","object":"response","status":"in_progress"}}',
            '{"type":"response.output_text.delta","response_id":"resp_size","delta":"partial","output_index":0}',
        ]
        if phase == "streaming"
        else []
    )

    async def send(_text):
        if phase in {"send", "idle-retry-send"}:
            raise rejection
        dispatched.set()

    async def receive():
        await dispatched.wait()
        event = next(messages, None)
        if event is None:
            raise rejection
        return event

    connection = SimpleNamespace(send=AsyncMock(side_effect=send), recv=receive, close=AsyncMock())
    upstream = WebsocketsUpstreamWebSocket(connection)
    healthy = _PromotionUpstreamWebSocket()
    connect = AsyncMock(side_effect=[*first_upstreams, upstream, healthy])
    legacy_stream = AsyncMock(side_effect=AssertionError("The test must exercise the HTTP bridge"))

    async def select_account(*args, **kwargs):
        return AccountSelection(account=account, error_message=None, error_code=None)

    async def fresh(self, target, **kwargs):
        return target

    monkeypatch.setattr(proxy_module.ProxyService, "_select_account_with_budget", select_account)
    monkeypatch.setattr(proxy_module.ProxyService, "_ensure_fresh_with_budget", fresh)
    monkeypatch.setattr(proxy_module.ProxyService, "_handle_stream_error", penalty)
    monkeypatch.setattr(proxy_module, "connect_responses_websocket", connect)
    monkeypatch.setattr(proxy_module, "core_stream_responses", legacy_stream)
    proxy_support.clear_upstream_websocket_transport_failure()
    try:
        body = {"model": "gpt-5.4", "input": _promotion_history(), "stream": True}
        response = await async_client.post("/v1/responses", json=body)
        assert response.status_code == status, response.text
        if phase == "streaming":
            events = [
                payload for block in response.text.split("\n\n") if (payload := parse_sse_data_json(block)) is not None
            ]
            assert any(event["type"] == "response.output_text.delta" for event in events)
            assert events[-1]["type"] == "response.failed"
            error = events[-1]["response"]["error"]
        else:
            error = response.json()["error"]
        assert error["code"] == code
        assert connect.await_count == len(first_upstreams) + 1
        connection.send.assert_awaited_once()
        if peer_first:
            assert error["type"] == "invalid_request_error"
            assert error["param"] == "input"
            penalty.assert_not_awaited()
            followup = await async_client.post("/v1/responses", json=body)
            assert followup.status_code == 200
            assert "response.completed" in followup.text
            assert connect.await_count == len(first_upstreams) + 2
            penalty.assert_not_awaited()
        legacy_stream.assert_not_called()
    finally:
        proxy_support.clear_upstream_websocket_transport_failure()
        await get_proxy_service_for_app(app_instance).drain_persistence_tasks(timeout_seconds=5.0)
