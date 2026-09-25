"""A client that disconnects before its streamed response starts, over a real socket.

Two windows, both before any response byte reaches the client:

* **The header wait.** OrcaRouter, OpenRouter, and openai-compat endpoints open
  the upstream before the response exists, so an upstream error can still be a
  JSON error with its real status. For a slow model that wait can be as long as
  the answer. A client leaving in it must cancel the upstream request and
  release its reservation now, not when the upstream eventually answers.
* **The response not yet started.** The handler returned a streaming response,
  and the client left before it ran. Starlette never closes the body iterator,
  so without an explicit close the settlement in its ``finally`` waits for
  garbage collection, leaving quota reserved until then.

Uvicorn runs on a real port and the client is a raw socket that is aborted, so
the disconnect is seen exactly as in production. Only the provider is faked,
by a real HTTP server.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import threading
from collections.abc import AsyncIterator, Callable

import aiohttp
import pytest
import pytest_asyncio
import uvicorn
from aiohttp import web
from sqlalchemy import select

from app.core.config.settings import get_settings
from app.core.utils.stream_close import ClosingStreamingResponse
from app.db.models import ApiKeyUsageReservation, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService, LimitRuleInput

pytestmark = pytest.mark.integration

_OPENAI_COMPAT_ENDPOINT_ID = "2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a"

# Every provider whose streamed chat goes through a dispatcher of its own.
_DISPATCH_MODULES = {
    "orcarouter": "app.modules.proxy.orcarouter_sidecar_dispatch",
    "openrouter": "app.modules.proxy.openrouter_sidecar_dispatch",
    "openai_compat": "app.modules.proxy.openai_compat_dispatch",
    "claude": "app.modules.proxy.claude_sidecar_dispatch",
}
# The providers that wait for the upstream's headers before responding.
_OPENS_BEFORE_RESPONDING = ("orcarouter", "openrouter", "openai_compat")


class _HeldUpstream:
    """An OpenAI-compatible upstream that answers only when released."""

    def __init__(self) -> None:
        self.request_arrived = asyncio.Event()
        self.release = asyncio.Event()
        self.request_cancelled = asyncio.Event()
        self.base_url = ""

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        await request.read()
        self.request_arrived.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.request_cancelled.set()
            raise
        response = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n')
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            self.request_cancelled.set()
            raise
        return response

    async def start(self) -> None:
        app = web.Application()
        app.router.add_post("/v1/chat/completions", self._handle)
        # Without handler cancellation aiohttp would keep the handler running
        # after codex-lb closed the connection, and the test could not see it.
        self._runner = web.AppRunner(app, handler_cancellation=True)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        port = self._runner.addresses[0][1]
        self.base_url = f"http://127.0.0.1:{port}/v1"

    async def stop(self) -> None:
        self.release.set()
        await self._runner.cleanup()


@pytest_asyncio.fixture
async def upstream(monkeypatch) -> AsyncIterator[_HeldUpstream]:
    for provider in ("ORCAROUTER", "OPENROUTER", "CLAUDE"):
        monkeypatch.setenv(f"CODEX_LB_{provider}_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    held = _HeldUpstream()
    await held.start()
    yield held
    await held.stop()
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def live_server(app_instance) -> AsyncIterator[str]:
    config = uvicorn.Config(app_instance, host="127.0.0.1", port=0, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.05)
    assert server.started, "uvicorn did not start"
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=30)


def _provider_settings(provider: str, base_url: str) -> tuple[dict[str, object], str]:
    """Dashboard settings routing one model to ``base_url``, and that model."""

    if provider == "orcarouter":
        return {
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarBaseUrl": base_url,
            "orcarouterSidecarApiKey": "sk-orca-synthetic",
            "orcarouterSidecarModelPrefixes": ["orcarouter/"],
        }, "orcarouter/z-ai/glm-5.3"
    if provider == "openrouter":
        return {
            "openrouterSidecarEnabled": True,
            "openrouterSidecarBaseUrl": base_url,
            "openrouterSidecarApiKey": "sk-or-synthetic",
            "openrouterSidecarModelPrefixes": ["z-ai/"],
        }, "z-ai/glm-5.3"
    if provider == "claude":
        return {
            "claudeSidecarEnabled": True,
            "claudeSidecarBaseUrl": base_url.removesuffix("/v1"),
            "claudeSidecarApiKey": "sk-claude-synthetic",
        }, "claude-opus-4-8"
    return {
        "openaiCompatEndpoints": [
            {
                "id": _OPENAI_COMPAT_ENDPOINT_ID,
                "name": "local",
                "enabled": True,
                "baseUrl": base_url,
                "modelPrefixes": [{"prefix": "compat/", "strip": True}],
            }
        ]
    }, "compat/glm-5.3"


async def _configure(live_server: str, provider: str, upstream: _HeldUpstream) -> tuple[str, str]:
    """Route ``provider`` to the fake upstream. Returns a limited API key and the model."""

    settings, model = _provider_settings(provider, upstream.base_url)
    async with aiohttp.ClientSession() as session:
        async with session.put(f"{live_server}/api/settings", json={**settings, "apiKeyAuthEnabled": True}) as resp:
            assert resp.status == 200, await resp.text()
    async with SessionLocal() as session:
        # A real limit, so the request holds a reservation the disconnect must release.
        created = await ApiKeysService(ApiKeysRepository(session)).create_key(
            ApiKeyCreateData(
                name="disconnect",
                allowed_models=None,
                limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=50_000)],
            )
        )
    return created.key, model


async def _send_and_hold(live_server: str, key: str, model: str) -> asyncio.StreamWriter:
    """Send a streamed chat request on a raw socket, and return the open connection."""

    host, port = live_server.removeprefix("http://").split(":")
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": "hi"}], "stream": True}).encode()
    _, writer = await asyncio.open_connection(host, int(port))
    writer.write(
        b"POST /v1/chat/completions HTTP/1.1\r\nHost: codex-lb\r\n"
        + b"Authorization: Bearer "
        + key.encode()
        + b"\r\nContent-Type: application/json\r\nContent-Length: "
        + str(len(body)).encode()
        + b"\r\n\r\n"
        + body
    )
    await writer.drain()
    return writer


async def _reservation_statuses() -> list[str]:
    async with SessionLocal() as session:
        return list((await session.execute(select(ApiKeyUsageReservation.status))).scalars())


async def _log_rows() -> list[tuple[str | None, str | None]]:
    async with SessionLocal() as session:
        return list((await session.execute(select(RequestLog.status, RequestLog.error_code))).tuples())


async def _eventually(check: Callable[[], object], *, timeout: float = 5.0) -> None:
    """Wait until ``check()`` is truthy. Async checks are awaited."""

    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        result = check()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"condition not met within {timeout}s")
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", _OPENS_BEFORE_RESPONDING)
async def test_leaving_during_the_header_wait_cancels_the_upstream_and_releases(
    live_server: str, upstream: _HeldUpstream, provider: str
) -> None:
    key, model = await _configure(live_server, provider, upstream)
    writer = await _send_and_hold(live_server, key, model)
    await asyncio.wait_for(upstream.request_arrived.wait(), timeout=10)
    assert await _reservation_statuses() == ["reserved"]

    writer.transport.abort()

    # The upstream never answers: everything below must follow from the
    # disconnect alone, not from a response arriving or timing out.
    await asyncio.wait_for(upstream.request_cancelled.wait(), timeout=5)
    await _eventually(lambda: _reservation_is("released"))
    await _eventually(_log_rows)
    assert await _log_rows() == [("cancelled", "client_disconnected")]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", sorted(_DISPATCH_MODULES))
async def test_leaving_before_the_response_starts_settles_without_waiting_for_gc(
    live_server: str, upstream: _HeldUpstream, monkeypatch, provider: str
) -> None:
    response_built = threading.Event()
    client_gone = threading.Event()

    class _StartsAfterTheClientLeft(ClosingStreamingResponse):
        """Runs only once the client is gone, so the body is never started by a read."""

        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            response_built.set()

        async def __call__(self, scope, receive, send) -> None:
            while not client_gone.is_set():
                await asyncio.sleep(0.02)
            await super().__call__(scope, receive, send)

    dispatch = importlib.import_module(_DISPATCH_MODULES[provider])
    monkeypatch.setattr(dispatch, "ClosingStreamingResponse", _StartsAfterTheClientLeft)
    upstream.release.set()  # the upstream answers at once
    key, model = await _configure(live_server, provider, upstream)

    writer = await _send_and_hold(live_server, key, model)
    # The handler has returned its response. Some providers have opened the
    # upstream by now, others open it only once the body runs.
    await _eventually(response_built.is_set, timeout=10)
    writer.transport.abort()
    client_gone.set()

    await _eventually(lambda: _reservation_is("released"))
    await _eventually(_log_rows)
    [(status, _)] = await _log_rows()
    assert status != "success"


async def _reservation_is(status: str) -> bool:
    return await _reservation_statuses() == [status]
