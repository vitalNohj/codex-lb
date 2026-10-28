"""The native xAI Responses route against a real CLIProxyAPI v8 binary.

Set ``CLIPROXYAPI_BIN`` to a CLIProxyAPI v8 executable to run these tests;
they are skipped otherwise. Each test starts the binary with two fake xAI
OAuth credentials whose ``base_url`` points at an in-process fake xAI
``/responses`` server, configures codex-lb to use it through the dashboard
settings API, and drives a multi-turn Codex conversation through codex-lb's
``/v1/responses``.

What reaches the fake xAI upstream is the proof:

* the encrypted reasoning returned on one turn arrives on the next turn
  byte-for-byte (the chat bridge dropped it, so every turn after a reasoning
  turn missed xAI's prompt cache);
* every turn carries the same ``prompt_cache_key`` and ``x-grok-conv-id``,
  equal to codex-lb's sticky pin id, and lands on the same credential, both
  when codex-lb pins the credential and when it leaves the choice to
  CLIProxyAPI's session affinity (before the first quota poll codex-lb knows
  no xAI login to pin);
* xAI's exact cost (``cost_in_usd_ticks``), cached and reasoning tokens land
  in the request log;
* CLIProxyAPI's ``routing.session-affinity`` is read and a warning is logged
  when it is off;
* with the switch off, the same conversation goes the old chat route and the
  reasoning is gone, which shows the test can tell the two routes apart.

The fake encrypted reasoning is high-entropy unpadded standard base64:
CLIProxyAPI's ``InspectGrokEncryptedContent`` strips anything else.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
import subprocess
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.clients.claude_sidecar import ClaudeSidecarClient
from app.core.clients.http import close_http_client, init_http_client
from app.core.config.settings import get_settings
from app.core.config.settings_cache import get_settings_cache
from app.db.models import CliproxyStickySession, RequestLog
from app.db.session import SessionLocal
from app.modules.claude_sidecar import session_affinity_guard
from app.modules.claude_sidecar.quota import snapshot_from_json
from app.modules.claude_sidecar.quota_poller import build_claude_sidecar_quota_poller
from app.modules.proxy.claude_sidecar_dispatch import load_sidecar_config
from app.modules.proxy.cliproxy_account_routing import candidates_from_snapshot

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("CLIPROXYAPI_BIN"), reason="CLIPROXYAPI_BIN is not set"),
]

_CLIENT_KEY = "lab-client-key"
_MANAGEMENT_KEY = "lab-mgmt-secret"
_MODEL = "grok-4.3"
_COST_TICKS = 123_456_789

_CONFIG = """\
config-version: 8
server:
  host: "127.0.0.1"
  port: {port}
management:
  allow-remote: false
  secret-key: "{secret}"
access:
  api-keys:
    - "{client_key}"
oauth:
  auth-dir: "./auths"
routing:
  strategy: "round-robin"
  session-affinity: true
request-retry: 0
"""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _blob(turn: int) -> str:
    """A unique, high-entropy, unpadded standard base64 reasoning blob."""

    raw = os.urandom(48 * 3) + turn.to_bytes(3, "big")
    return base64.b64encode(raw).decode().rstrip("=")


@dataclass
class _FakeXai:
    """xAI's ``/responses``: records each request and answers with reasoning."""

    requests: list[dict] = field(default_factory=list)
    blobs: list[str] = field(default_factory=list)

    async def handle(self, request: web.Request) -> web.StreamResponse:
        body = await request.json()
        credential = request.path.split("/")[1]
        headers = {name.lower(): value for name, value in request.headers.items()}
        self.requests.append({"credential": credential, "headers": headers, "body": body})
        blob = _blob(len(self.blobs))
        self.blobs.append(blob)
        response = self._response(body, blob)
        if body.get("stream"):
            stream = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await stream.prepare(request)
            for event in self._events(response):
                await stream.write(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode())
            await stream.write_eof()
            return stream
        return web.json_response(response)

    @staticmethod
    def _response(body: dict, blob: str) -> dict:
        return {
            "id": "resp_fake",
            "object": "response",
            "created_at": 1,
            "status": "completed",
            "model": body.get("model"),
            "output": [
                {"id": "rs_fake", "type": "reasoning", "summary": [], "encrypted_content": blob},
                {
                    "id": "msg_fake",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "ok", "annotations": []}],
                },
            ],
            "usage": {
                "input_tokens": 1200,
                "input_tokens_details": {"cached_tokens": 1024},
                "output_tokens": 80,
                "output_tokens_details": {"reasoning_tokens": 48},
                "total_tokens": 1280,
                "cost_in_usd_ticks": _COST_TICKS,
            },
        }

    @staticmethod
    def _events(response: dict) -> list[dict]:
        reasoning, message = response["output"]
        in_progress = {**response, "status": "in_progress", "output": [], "usage": None}
        return [
            {"type": "response.created", "sequence_number": 0, "response": in_progress},
            {"type": "response.output_item.added", "sequence_number": 1, "output_index": 0, "item": reasoning},
            {"type": "response.output_item.done", "sequence_number": 2, "output_index": 0, "item": reasoning},
            {"type": "response.output_item.added", "sequence_number": 3, "output_index": 1, "item": message},
            {
                "type": "response.output_text.delta",
                "sequence_number": 4,
                "output_index": 1,
                "content_index": 0,
                "item_id": "msg_fake",
                "delta": "ok",
            },
            {"type": "response.output_item.done", "sequence_number": 5, "output_index": 1, "item": message},
            {"type": "response.completed", "sequence_number": 6, "response": response},
        ]


@pytest_asyncio.fixture
async def fake_xai() -> AsyncIterator[tuple[_FakeXai, int]]:
    fake = _FakeXai()
    app = web.Application()
    app.router.add_post("/{credential}/v1/responses", fake.handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = _free_port()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    try:
        yield fake, port
    finally:
        await runner.cleanup()


@pytest.fixture
def cliproxy(tmp_path: Path, fake_xai: tuple[_FakeXai, int]) -> Iterator[str]:
    _fake, upstream_port = fake_xai
    binary = os.environ["CLIPROXYAPI_BIN"]
    port = _free_port()
    (tmp_path / "config.yaml").write_text(_CONFIG.format(port=port, secret=_MANAGEMENT_KEY, client_key=_CLIENT_KEY))
    auths = tmp_path / "auths"
    auths.mkdir()
    for index in (1, 2):
        (auths / f"xai-oauth-fake{index}.json").write_text(
            json.dumps(
                {
                    "type": "xai",
                    "auth_kind": "oauth",
                    "access_token": f"FAKE-oauth-access-{index}",
                    "refresh_token": f"FAKE-refresh-{index}",
                    "expired": "2099-01-01T00:00:00Z",
                    "email": f"fake{index}@example.com",
                    "base_url": f"http://127.0.0.1:{upstream_port}/cred{index}/v1",
                    "prefix": f"oa{index}",
                }
            )
        )
    home = tmp_path / "home"
    home.mkdir()
    log = (tmp_path / "cliproxy.log").open("wb")
    process = subprocess.Popen(
        [binary, "-config", str(tmp_path / "config.yaml")],
        cwd=tmp_path,
        stdout=log,
        stderr=log,
        env={**os.environ, "HOME": str(home)},
    )
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        log.close()


async def _wait_ready(base_url: str) -> None:
    headers = {"Authorization": f"Bearer {_CLIENT_KEY}"}
    async with aiohttp.ClientSession() as session:
        for _ in range(150):
            try:
                async with session.get(f"{base_url}/v1/models", headers=headers) as resp:
                    if resp.status == 200:
                        ids = {item["id"] for item in (await resp.json())["data"]}
                        if {_MODEL, f"oa1/{_MODEL}", f"oa2/{_MODEL}"} <= ids:
                            return
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(0.1)
    raise AssertionError("CLIProxyAPI did not start with both fake xAI credentials")


@pytest.fixture
def fresh_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def quota_poll_first() -> bool:
    """Whether codex-lb runs one quota poll before the conversation.

    The poll lists the xAI OAuth logins, which makes them codex-lb pin
    candidates. A test parametrizes this to ``False`` to prove the
    session-affinity fallback that serves a conversation before that poll.
    """

    return True


@pytest_asyncio.fixture
async def codex_lb(
    monkeypatch: pytest.MonkeyPatch,
    app_instance,
    cliproxy: str,
    fresh_settings,
    quota_poll_first: bool,
) -> AsyncIterator[AsyncClient]:
    del fresh_settings
    await _wait_ready(cliproxy)
    await init_http_client()
    try:

        async def _drain(response) -> None:
            del response
            service = getattr(app_instance.state, "proxy_service", None)
            if service is not None and hasattr(service, "drain_persistence_tasks"):
                await service.drain_persistence_tasks(timeout_seconds=5)

        async with AsyncClient(
            transport=ASGITransport(app=app_instance),
            base_url="http://testserver",
            event_hooks={"response": [_drain]},
            timeout=30,
        ) as client:
            response = await client.put(
                "/api/settings",
                json={
                    "claudeSidecarEnabled": True,
                    "claudeSidecarBaseUrl": cliproxy,
                    "claudeSidecarApiKey": _CLIENT_KEY,
                    "claudeSidecarManagementKey": _MANAGEMENT_KEY,
                    "claudeSidecarFullModels": [_MODEL],
                },
            )
            assert response.status_code == 200, response.text
            if quota_poll_first:
                # One quota poll, as the running service does, so codex-lb knows
                # both credentials and pins the conversation to one of them.
                await build_claude_sidecar_quota_poller()._poll_locked()
            yield client
    finally:
        await close_http_client()


def _turn_input(history: list[dict], text: str) -> list[dict]:
    return [*history, {"role": "user", "content": [{"type": "input_text", "text": text}]}]


async def _converse(client: AsyncClient, *, turns: int, stream: bool) -> list[dict]:
    """Run a Codex-style conversation: each turn replays the full history."""

    history: list[dict] = []
    outputs: list[dict] = []
    for turn in range(turns):
        request_input = _turn_input(history, f"step {turn}")
        payload = {
            "model": _MODEL,
            "instructions": "You are a careful coding agent.",
            "input": request_input,
            "include": ["reasoning.encrypted_content"],
            "reasoning": {"effort": "high", "summary": "detailed"},
            "store": False,
            "stream": stream,
        }
        if stream:
            async with client.stream("POST", "/v1/responses", json=payload) as response:
                body = await response.aread()
            assert response.status_code == 200, body
            completed = [
                json.loads(line.removeprefix("data: "))
                for line in body.decode().splitlines()
                if line.startswith("data: ") and '"response.completed"' in line
            ]
            assert len(completed) == 1, body
            output = completed[0]["response"]["output"]
        else:
            response = await client.post("/v1/responses", json=payload)
            assert response.status_code == 200, response.text
            output = response.json()["output"]
        outputs.append({"output": output})
        history = [*request_input, *output]
    return outputs


def _reasoning_blobs(items: list[dict]) -> list[str]:
    return [item["encrypted_content"] for item in items if item.get("type") == "reasoning"]


async def _cliproxy_pins() -> list[tuple[str, str]]:
    async with SessionLocal() as session:
        rows = (await session.execute(select(CliproxyStickySession))).scalars().all()
    return [(row.key, row.account_id) for row in rows]


async def _account_for_upstream_credential(credential: str) -> str:
    """The codex-lb account id of the fake credential named ``credN``."""

    settings = await get_settings_cache().get()
    snapshot = snapshot_from_json(settings.claude_sidecar_quota_state_json)
    index = credential.removeprefix("cred")
    [candidate] = [
        item
        for item in candidates_from_snapshot(snapshot, now=datetime.now(timezone.utc))
        if item.name == f"xai-oauth-fake{index}.json"
    ]
    return candidate.account_id


async def _assert_native_conversation(
    client: AsyncClient,
    fake: _FakeXai,
    *,
    stream: bool,
    pinned: bool = True,
) -> None:
    turns = 4
    outputs = await _converse(client, turns=turns, stream=stream)

    assert len(fake.requests) == turns
    # The reasoning codex-lb returned is xAI's, unchanged.
    for turn, output in enumerate(outputs):
        assert _reasoning_blobs(output["output"]) == [fake.blobs[turn]]
    # Every earlier turn's encrypted reasoning reaches xAI byte-for-byte, in order.
    for turn, request in enumerate(fake.requests):
        assert _reasoning_blobs(request["body"]["input"]) == fake.blobs[:turn]
    # One conversation, one cache key, one conv id, one credential.
    cache_keys = {request["body"].get("prompt_cache_key") for request in fake.requests}
    conv_ids = {request["headers"].get("x-grok-conv-id") for request in fake.requests}
    credentials = {request["credential"] for request in fake.requests}
    assert len(cache_keys) == 1 and None not in cache_keys and "" not in cache_keys
    assert conv_ids == cache_keys
    assert len(credentials) == 1
    if not pinned:
        # No codex-lb pin: CLIProxyAPI's session affinity alone kept the
        # conversation on one credential, keyed by the same cache key.
        assert await _cliproxy_pins() == []
        return
    # codex-lb pinned the conversation itself, under the same id: one sticky
    # row whose key ends in the cache key xAI saw, owned by the one credential
    # (the prefix codex-lb put on the model, which CLIProxyAPI stripped).
    [cache_key] = cache_keys
    [credential] = credentials
    pins = await _cliproxy_pins()
    assert len(pins) == 1
    pin_key, pin_account = pins[0]
    assert pin_key.endswith(f":{cache_key}")
    assert pin_account == await _account_for_upstream_credential(credential)
    # Fields the chat bridge dropped or rewrote arrive as the client sent them.
    for request in fake.requests:
        body = request["body"]
        assert body["instructions"] == "You are a careful coding agent."
        assert body["reasoning"]["effort"] == "high"
        assert body["reasoning"]["summary"] == "detailed"
        assert body["model"] == _MODEL


@pytest.mark.asyncio
async def test_native_route_round_trips_encrypted_reasoning_non_streaming(codex_lb, fake_xai) -> None:
    fake, _port = fake_xai
    await _assert_native_conversation(codex_lb, fake, stream=False)


@pytest.mark.asyncio
async def test_native_route_round_trips_encrypted_reasoning_streaming(codex_lb, fake_xai) -> None:
    fake, _port = fake_xai
    await _assert_native_conversation(codex_lb, fake, stream=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_poll_first", [False])
async def test_native_route_without_a_codex_lb_pin_stays_on_one_credential(
    codex_lb, fake_xai, quota_poll_first
) -> None:
    """Before the first quota poll codex-lb knows no xAI login to pin, so
    CLIProxyAPI's session affinity is what keeps a conversation's cache."""

    del quota_poll_first
    fake, _port = fake_xai
    await _assert_native_conversation(codex_lb, fake, stream=True, pinned=False)


@pytest.mark.asyncio
async def test_native_route_records_xai_cost_and_cached_tokens(codex_lb, fake_xai) -> None:
    await _converse(codex_lb, turns=2, stream=True)

    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    sidecar_logs = [log for log in logs if log.source == "claude_sidecar"]
    assert len(sidecar_logs) == 2
    for log in sidecar_logs:
        assert log.status == "success"
        assert log.cached_input_tokens == 1024
        assert log.reasoning_tokens == 48
        assert log.cost_usd == pytest.approx(_COST_TICKS / 1e10)
        assert log.cost_source == "upstream_billed"


@pytest.mark.asyncio
async def test_switch_off_returns_xai_to_the_chat_bridge(monkeypatch, codex_lb, fake_xai) -> None:
    """The control: the old route drops the reasoning this route keeps."""

    fake, _port = fake_xai
    monkeypatch.setenv("CODEX_LB_CLIPROXY_XAI_NATIVE_RESPONSES_ENABLED", "false")
    get_settings.cache_clear()

    await _converse(codex_lb, turns=2, stream=False)

    assert len(fake.requests) == 2
    assert _reasoning_blobs(fake.requests[1]["body"]["input"]) == []
    # The bridge turns instructions into a developer message.
    assert fake.requests[1]["body"].get("instructions") in (None, "")


@pytest.mark.asyncio
async def test_session_affinity_is_read_from_the_real_binary(codex_lb, caplog) -> None:
    session_affinity_guard.reset_session_affinity_guard()
    config = await load_sidecar_config()
    assert config is not None
    client = ClaudeSidecarClient(config)

    assert await session_affinity_guard.check_cliproxy_session_affinity(client) is True
    await client.set_session_affinity(False)
    caplog.set_level("WARNING", logger=session_affinity_guard.__name__)
    assert await session_affinity_guard.check_cliproxy_session_affinity(client) is False
    assert any("session-affinity is off" in record.getMessage() for record in caplog.records)
    await client.set_session_affinity(True)
