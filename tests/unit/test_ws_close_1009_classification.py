from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from app.core.clients.proxy_websocket import (
    CodexUpstreamWebSocket,
    UpstreamWebSocketTransportError,
    WebsocketsUpstreamWebSocket,
    _raise_websocket_send_error,
)
from app.modules.proxy._service.streaming.helpers import _classify_upstream_close


@pytest.mark.asyncio
async def test_send_error_adapter_classifies_proven_peer_1009() -> None:
    frame = Close(1009, "untrusted peer reason")
    exc = ConnectionClosedError(frame, frame, True)
    with pytest.raises(UpstreamWebSocketTransportError) as error:
        await _raise_websocket_send_error(exc, uses_proxy=False)
    assert error.value.error_code == "payload_too_large"
    assert "reduce the request size" in str(error.value)
    assert frame.reason not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("method,payload", [("send_text", "{}"), ("send_bytes", b"{}")])
@pytest.mark.parametrize(
    ("received", "sent", "peer_first", "code"),
    [
        (1009, 1009, True, "payload_too_large"),
        (1009, None, None, "payload_too_large"),
        (1009, 1009, False, "upstream_unavailable"),
        (None, 1009, None, "upstream_unavailable"),
        (1000, 1009, False, "upstream_unavailable"),
        (1008, 1008, True, "upstream_unavailable"),
    ],
)
async def test_send_needs_peer_first_1009(method, payload, received, sent, peer_first, code):
    close = ConnectionClosedError(
        Close(received, "") if received is not None else None,
        Close(sent, "") if sent is not None else None,
        peer_first,
    )
    adapter = WebsocketsUpstreamWebSocket(SimpleNamespace(send=AsyncMock(side_effect=close)))
    with pytest.raises(UpstreamWebSocketTransportError) as error:
        await getattr(adapter, method)(payload)
    assert error.value.error_code == code


@pytest.mark.asyncio
@pytest.mark.parametrize("preserve_close_semantics", [False, True])
@pytest.mark.parametrize("peer_first", [False, True])
async def test_websockets_receive_needs_peer_first_1009(preserve_close_semantics, peer_first):
    close = Close(1009, "")
    error = ConnectionClosedError(close, close, peer_first)
    adapter = WebsocketsUpstreamWebSocket(
        SimpleNamespace(recv=AsyncMock(side_effect=error)),
        preserve_close_semantics=preserve_close_semantics,
    )
    message = await adapter.receive()
    assert message.kind == ("close" if preserve_close_semantics else "error")
    assert message.close_code == 1009
    assert message.error_code == ("payload_too_large" if peer_first else None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "code"),
    [
        (aiohttp.WSMessage(aiohttp.WSMsgType.CLOSE, 1009, "too big"), "payload_too_large"),
        (aiohttp.WSMessage(aiohttp.WSMsgType.CLOSED, None, None), None),
        (aiohttp.WSMessage(aiohttp.WSMsgType.ERROR, aiohttp.WebSocketError(1009, "over limit"), None), None),
    ],
)
async def test_routed_receive_requires_an_actual_peer_close_frame(message, code):
    adapter = CodexUpstreamWebSocket(SimpleNamespace(receive=AsyncMock(return_value=message), close_code=1009))
    result = await adapter.receive()
    assert result.close_code == 1009
    assert result.error_code == code


@pytest.mark.parametrize(
    ("close_code", "events", "error_code", "classification"),
    [
        (1009, 0, "payload_too_large", "payload_too_large"),
        (1009, 5, "payload_too_large", "payload_too_large"),
        (1009, 0, None, "ambiguous_size_limit"),
        (1000, 0, None, "clean"),
        (1000, 3, None, "transient"),
        (1006, 0, None, "transient"),
        (None, 0, None, "transient"),
    ],
)
def test_classify_upstream_close(close_code, events, error_code, classification):
    assert _classify_upstream_close(close_code, response_events_seen=events, error_code=error_code) == classification
