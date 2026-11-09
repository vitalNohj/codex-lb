from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Callable
from typing import Any

import pytest
import pytest_asyncio

from app.core.clients.proxy_websocket import UpstreamWebSocketMessage
from app.dependencies import get_proxy_service_for_app
from app.modules.proxy import service as proxy_module
from app.modules.proxy.load_balancer import AccountSelection
from tests.integration.test_http_responses_bridge import (
    _cleanup_http_bridge_sessions as cleanup_http_bridge_sessions,  # noqa: F401
)
from tests.integration.test_http_responses_bridge import (
    _FakeBridgeUpstreamWebSocket,
    _get_account,
    _import_account,
    _install_bridge_settings_with_limits,
    _PreviousResponseNotFoundUpstreamWebSocket,
    _promotion_history,
)

pytestmark = pytest.mark.integration
_LIMIT_CODE = "websocket_connection_limit_reached"


class _AgeLimitedUpstream(_FakeBridgeUpstreamWebSocket):
    def __init__(self, *, output_first: bool = False, error_shape: str = "error") -> None:
        super().__init__("resp_expired")
        self.output_first = output_first
        self.error_shape = error_shape

    async def send_text(self, text: str) -> None:
        self.sent_text.append(text)
        if self.output_first:
            for payload in (
                {"type": "response.created", "response": {"id": "resp_partial", "status": "in_progress"}},
                {"type": "response.output_text.delta", "response_id": "resp_partial", "delta": "partial"},
            ):
                await self._messages.put(UpstreamWebSocketMessage("text", text=json.dumps(payload)))
        error = {
            "type": "invalid_request_error",
            "code": _LIMIT_CODE,
            "message": "Responses websocket connection limit reached (60 minutes). "
            "Create a new websocket connection to continue.",
        }
        if self.error_shape == "response.failed":
            payload = {"type": "response.failed", "response": {"status": "failed", "error": error}}
        elif self.error_shape == "typeless":
            payload = {"error": error}
        else:
            payload = {"type": "error", "error": error}
        await self._messages.put(UpstreamWebSocketMessage("text", text=json.dumps(payload)))


class _TextOutputUpstream(_FakeBridgeUpstreamWebSocket):
    async def send_text(self, text: str) -> None:
        await super().send_text(text)
        created = self._messages.get_nowait()
        completed = self._messages.get_nowait()
        self._messages.put_nowait(created)
        self._messages.put_nowait(
            UpstreamWebSocketMessage(
                "text",
                text=json.dumps(
                    {
                        "type": "response.output_text.delta",
                        "response_id": f"{self.response_id_prefix}_{len(self.sent_text)}",
                        "delta": "OK",
                    }
                ),
            )
        )
        self._messages.put_nowait(completed)


@pytest_asyncio.fixture
async def rotation_transport(async_client, monkeypatch):
    _install_bridge_settings_with_limits(monkeypatch, enabled=True, instance_id=socket.gethostname())
    account_id = await _import_account(async_client, "acc_rotation", "rotation@example.com")
    account = await _get_account(account_id)
    upstreams: list[_FakeBridgeUpstreamWebSocket] = []
    opened_accounts: list[str] = []
    selection_calls: list[dict[str, Any]] = []
    factory: Callable[[], _FakeBridgeUpstreamWebSocket] = _FakeBridgeUpstreamWebSocket

    async def select_account(self, deadline, **kwargs):
        selection_calls.append(kwargs)
        return AccountSelection(account=account, error_message=None, error_code=None)

    async def ensure_fresh(self, target, **kwargs):
        return target

    async def connect(headers, access_token, account_id_header, **kwargs):
        opened_accounts.append(account_id_header)
        upstream = factory()
        upstreams.append(upstream)
        return upstream

    async def unexpected_raw_transport(*args, **kwargs):
        raise AssertionError("A connection-rotation test must not bypass the websocket bridge")
        yield ""  # pragma: no cover -- keep the upstream async-generator contract.

    monkeypatch.setattr(proxy_module.ProxyService, "_select_account_with_budget", select_account)
    monkeypatch.setattr(proxy_module.ProxyService, "_ensure_fresh_with_budget", ensure_fresh)
    monkeypatch.setattr(proxy_module, "connect_responses_websocket", connect)
    monkeypatch.setattr(proxy_module, "core_stream_responses", unexpected_raw_transport)

    def set_factory(replacement: Callable[[], _FakeBridgeUpstreamWebSocket]) -> None:
        nonlocal factory
        factory = replacement

    return upstreams, opened_accounts, selection_calls, set_factory


def _payload(*, stream: bool = False) -> dict[str, Any]:
    return {
        "model": "gpt-5.1",
        "instructions": "Return exactly OK.",
        "input": "hello",
        "prompt_cache_key": "rotation-thread",
        "stream": stream,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("error_shape", ["error", "typeless", "response.failed"])
async def test_expired_upstream_retries_before_output_on_same_account(
    async_client, app_instance, rotation_transport, error_shape
):
    upstreams, opened_accounts, selections, set_factory = rotation_transport
    set_factory(
        lambda: (
            _AgeLimitedUpstream(error_shape=error_shape)
            if not upstreams
            else _FakeBridgeUpstreamWebSocket("resp_fresh")
        )
    )

    response = await asyncio.wait_for(async_client.post("/v1/responses", json=_payload()), timeout=5)

    assert response.status_code == 200, response.text
    assert response.json()["id"] == "resp_fresh_1"
    assert len(upstreams) == 2
    assert [len(upstream.sent_text) for upstream in upstreams] == [1, 1]
    assert upstreams[0].closed
    assert opened_accounts[0] == opened_accounts[1]
    assert selections[-1]["fallback_on_preferred_account_unavailable"] is False
    assert json.loads(upstreams[0].sent_text[0]) == json.loads(upstreams[1].sent_text[0])
    service = get_proxy_service_for_app(app_instance)
    session = next(iter(service._http_bridge_sessions.values()))
    assert session.upstream_reader is not None
    session.upstream_reader.cancel()
    await asyncio.gather(session.upstream_reader, return_exceptions=True)
    assert session.closed


@pytest.mark.asyncio
async def test_old_idle_upstream_rotates_before_next_turn(async_client, app_instance, rotation_transport):
    upstreams, opened_accounts, selections, _ = rotation_transport
    first = await async_client.post("/v1/responses", json=_payload())
    assert first.status_code == 200, first.text
    service = get_proxy_service_for_app(app_instance)
    session = next(iter(service._http_bridge_sessions.values()))
    session.upstream_connected_at -= 3301
    original_headers = dict(session.headers)
    original_affinity = session.affinity
    old_connected_at = session.upstream_connected_at

    second = await asyncio.wait_for(async_client.post("/v1/responses", json=_payload()), timeout=5)

    assert second.status_code == 200, second.text
    assert len(upstreams) == 2
    assert [len(upstream.sent_text) for upstream in upstreams] == [1, 1]
    assert upstreams[0].closed
    assert opened_accounts[0] == opened_accounts[1]
    assert selections[-1]["fallback_on_preferred_account_unavailable"] is False
    assert session.headers == original_headers
    assert session.affinity == original_affinity
    assert session.upstream_connected_at > old_connected_at


@pytest.mark.asyncio
async def test_expired_upstream_does_not_replay_after_output(async_client, rotation_transport):
    upstreams, _, _, set_factory = rotation_transport
    set_factory(lambda: _AgeLimitedUpstream(output_first=True))

    response = await asyncio.wait_for(async_client.post("/v1/responses", json=_payload(stream=True)), timeout=5)

    assert response.status_code == 200, response.text
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")]
    assert any(event.get("delta") == "partial" for event in events)
    assert len(upstreams) == 1
    assert len(upstreams[0].sent_text) == 1
    assert events[-1]["type"] == "response.failed"
    assert events[-1]["response"]["error"]["code"] == "upstream_unavailable"
    assert _LIMIT_CODE not in response.text


@pytest.mark.asyncio
async def test_expired_upstream_retries_only_once(async_client, rotation_transport):
    upstreams, opened_accounts, _, set_factory = rotation_transport
    set_factory(_AgeLimitedUpstream)

    response = await asyncio.wait_for(async_client.post("/v1/responses", json=_payload()), timeout=5)

    assert response.status_code == 502, response.text
    assert response.json()["error"]["code"] == "upstream_unavailable"
    assert len(upstreams) == 2
    assert opened_accounts[0] == opened_accounts[1]
    assert [len(upstream.sent_text) for upstream in upstreams] == [1, 1]


@pytest.mark.asyncio
async def test_promoted_chat_completion_hides_upstream_connection_limit(async_client, rotation_transport):
    upstreams, opened_accounts, _, set_factory = rotation_transport
    set_factory(lambda: _AgeLimitedUpstream() if not upstreams else _TextOutputUpstream("resp_chat"))

    response = await asyncio.wait_for(
        async_client.post(
            "/v1/chat/completions",
            json={"model": "gpt-5.1", "messages": _promotion_history()},
        ),
        timeout=5,
    )

    assert response.status_code == 200, response.text
    assert response.json()["choices"][0]["message"]["content"] == "OK"
    assert len(upstreams) == 2
    assert opened_accounts[0] == opened_accounts[1]
    assert _LIMIT_CODE not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("reactive", [False, True])
async def test_rotation_refuses_a_different_account(
    async_client, app_instance, monkeypatch, rotation_transport, reactive
):
    upstreams, _, _, set_factory = rotation_transport
    other_id = await _import_account(async_client, "acc_other_rotation", "other-rotation@example.com")
    other_account = await _get_account(other_id)
    select_original = proxy_module.ProxyService._select_account_with_budget

    async def select_account(self, deadline, **kwargs):
        if kwargs.get("request_stage") == "reattach":
            return AccountSelection(account=other_account, error_message=None, error_code=None)
        return await select_original(self, deadline, **kwargs)

    monkeypatch.setattr(proxy_module.ProxyService, "_select_account_with_budget", select_account)
    if reactive:
        set_factory(_AgeLimitedUpstream)
    else:
        first = await async_client.post("/v1/responses", json=_payload())
        assert first.status_code == 200, first.text
        service = get_proxy_service_for_app(app_instance)
        session = next(iter(service._http_bridge_sessions.values()))
        session.upstream_connected_at -= 3301

    response = await asyncio.wait_for(async_client.post("/v1/responses", json=_payload()), timeout=5)

    assert response.status_code == 502, response.text
    assert len(upstreams) == 1
    assert len(upstreams[0].sent_text) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reactive, recovery_limit", [(False, False), (True, False), (True, True)])
async def test_rotated_connection_uses_existing_previous_response_not_found_recovery(
    async_client, app_instance, rotation_transport, reactive, recovery_limit
):
    upstreams, opened_accounts, _, set_factory = rotation_transport
    first = await async_client.post("/v1/responses", json=_payload())
    assert first.status_code == 200, first.text
    service = get_proxy_service_for_app(app_instance)
    session = next(iter(service._http_bridge_sessions.values()))
    if reactive:
        # The reused socket rejects the next turn at its age limit.
        async def expired_send(text):
            expired = _AgeLimitedUpstream()
            await expired.send_text(text)
            upstreams[0].sent_text.append(text)
            await upstreams[0]._messages.put(await expired.receive())

        upstreams[0].send_text = expired_send
    else:
        session.upstream_connected_at -= 3301
    set_factory(
        lambda: (
            _PreviousResponseNotFoundUpstreamWebSocket()
            if len(upstreams) == 1
            else (_AgeLimitedUpstream() if recovery_limit else _FakeBridgeUpstreamWebSocket("resp_recovered"))
        )
    )
    payload = _payload()
    payload["input"] = "continue"
    payload["previous_response_id"] = first.json()["id"]

    second = await asyncio.wait_for(async_client.post("/v1/responses", json=payload), timeout=5)

    if recovery_limit:
        assert second.status_code == 502, second.text
        assert second.json()["error"]["code"] == "upstream_unavailable"
    else:
        assert second.status_code == 200, second.text
        assert second.json()["id"] == "resp_recovered_1"
    assert len(upstreams) == 3
    assert len(set(opened_accounts)) == 1
    assert json.loads(upstreams[1].sent_text[0])["previous_response_id"] == first.json()["id"]
    assert _LIMIT_CODE not in second.text


class _ConnectionScopedStoreUpstream(_PreviousResponseNotFoundUpstreamWebSocket):
    async def send_text(self, text: str) -> None:
        if json.loads(text).get("previous_response_id"):
            await super().send_text(text)
        else:
            await _FakeBridgeUpstreamWebSocket.send_text(self, text)


@pytest.mark.asyncio
async def test_rotation_preserves_full_history_on_fresh_connection(async_client, app_instance, rotation_transport):
    upstreams, opened_accounts, _, set_factory = rotation_transport
    headers = {"session_id": "rotation-full-history"}
    first = await asyncio.wait_for(async_client.post("/v1/responses", json=_payload(), headers=headers), timeout=5)
    assert first.status_code == 200, first.text
    service = get_proxy_service_for_app(app_instance)
    session = next(iter(service._http_bridge_sessions.values()))
    session.upstream_connected_at -= 3301
    set_factory(_ConnectionScopedStoreUpstream)
    full_history = [
        {"role": "user", "content": [{"type": "input_text", "text": "hello"}]},
        {"role": "user", "content": [{"type": "input_text", "text": "again"}]},
    ]
    second_payload = _payload()
    second_payload["input"] = full_history

    second = await asyncio.wait_for(async_client.post("/v1/responses", json=second_payload, headers=headers), timeout=5)

    assert second.status_code == 200, second.text
    assert len(set(opened_accounts)) == 1
    fresh_frames = [json.loads(text) for upstream in upstreams[1:] for text in upstream.sent_text]
    assert len(upstreams) == 2
    assert fresh_frames[-1].get("previous_response_id") is None
    assert fresh_frames[-1]["input"] == full_history
