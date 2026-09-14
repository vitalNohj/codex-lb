"""An unconfigured OpenCode Go integration must not send request content anywhere.

Reported by the verification lane: after a successful Settings *clear*, an
enabled Go integration still POSTed to the upstream with no ``Authorization``
header and mapped the resulting 401 to 503.

The reason that is not merely a wasted round trip is the request **body**. The
outbound payload carries the end user's prompt, and it leaves the process before
any credential check happens. That the upstream returns no useful content proves
nothing about what was disclosed to it - disclosure already occurred on the way
out. An integration with no credential has no business addressing the upstream
at all.

Every check here drives the real ASGI app against an isolated loopback sink that
records exactly what arrives. Synthetic prompt text, synthetic keys, no real
credential and no real upstream.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytestmark = pytest.mark.integration

#: Distinctive so its presence in a captured body is unambiguous.
_PROMPT_CANARY = "SYNTHETIC-PROMPT-CANARY-must-not-leave-the-process"


class _RecordingSink:
    """A loopback HTTP sink that records every request it receives."""

    def __init__(self) -> None:
        self.requests: list[dict[str, str | None]] = []
        sink = self

        class _Handler(BaseHTTPRequestHandler):
            def _record(self) -> None:
                length = int(self.headers.get("Content-Length", 0) or 0)
                body = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
                sink.requests.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "body": body,
                    }
                )
                payload = b'{"type":"error","error":{"type":"AuthError","message":"Missing API key."}}'
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = _record
            do_POST = _record

            def log_message(self, *_args: object) -> None:
                pass

        self._server = HTTPServer(("127.0.0.1", 0), _Handler)
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}/zen/go/v1"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> _RecordingSink:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()

    @property
    def leaked_prompt(self) -> bool:
        return any(_PROMPT_CANARY in (entry["body"] or "") for entry in self.requests)


@pytest.fixture
def trap_other_providers(monkeypatch):
    """Fail loudly if an unconfigured Go request reaches any other provider.

    The sink alone cannot prove this. On a test database with no Codex accounts
    a fall-through also yields 503, so "sink empty + 503" is satisfied both by a
    correct local refusal and by the prompt being rerouted to Codex - the very
    outcome this boundary exists to prevent. These traps make the two
    distinguishable.
    """

    import app.modules.proxy.api as proxy_api
    from app.modules.proxy.service import ProxyService

    tripped: list[str] = []

    def _trap(name: str):
        def _fail(*_args: object, **_kwargs: object):
            tripped.append(name)
            raise AssertionError(f"unconfigured OpenCode Go request reached {name}")

        return _fail

    for name in (
        "proxy_chat_to_sidecar",
        "proxy_chat_to_openrouter",
        "proxy_chat_to_orcarouter",
        "proxy_chat_to_ollama",
        "proxy_chat_to_omniroute",
        "_select_chat_model_source",
        "_select_responses_model_source",
    ):
        if hasattr(proxy_api, name):
            monkeypatch.setattr(proxy_api, name, _trap(name), raising=True)
    monkeypatch.setattr(ProxyService, "stream_responses", _trap("ProxyService.stream_responses"), raising=True)
    return tripped


def _assert_not_configured(response) -> None:
    """The refusal must be Go's own, with the documented shape."""

    assert response.status_code == 503, response.text
    body = response.json()
    assert body["error"]["code"] == "opencode_go_not_configured", body
    assert response.headers.get("retry-after") == "60"


@pytest.fixture
def sink():
    with _RecordingSink() as recording_sink:
        yield recording_sink


@pytest.fixture
def allow_loopback_base_url(monkeypatch):
    """Permit the loopback sink URL through the Go-endpoint guard.

    The guard accepts only the documented endpoint, which is correct and is
    covered elsewhere. Relaxing it *only* here is what lets this file test the
    credential boundary against a real socket instead of the real upstream.
    """

    from app.core.config import opencode_go_endpoint

    real = opencode_go_endpoint.is_opencode_go_base_url

    def _permissive(base_url: str) -> bool:
        return base_url.strip().rstrip("/").startswith("http://127.0.0.1:") or real(base_url)

    for module in (
        "app.core.config.opencode_go_endpoint",
        "app.core.config.settings",
        "app.modules.settings.schemas",
        "app.core.clients.opencode_go_sidecar",
    ):
        monkeypatch.setattr(f"{module}.is_opencode_go_base_url", _permissive, raising=False)


async def _configure(async_client, sink, *, api_key: str | None) -> None:
    body: dict[str, object] = {
        "opencodeGoSidecarEnabled": True,
        "opencodeGoSidecarBaseUrl": sink.base_url,
        "opencodeGoSidecarModelPrefixes": [{"prefix": "opencode-go/", "strip": True}],
        "opencodeGoSidecarFullModels": ["glm-5.3"],
    }
    if api_key is None:
        body["opencodeGoSidecarClearApiKey"] = True
    else:
        body["opencodeGoSidecarApiKey"] = api_key
    response = await async_client.put("/api/settings", json=body)
    assert response.status_code == 200, f"settings PUT failed: {response.status_code} {response.text[:400]}"


async def _api_key(name: str):
    from app.db.session import SessionLocal
    from app.modules.api_keys.repository import ApiKeysRepository
    from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService

    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        return await service.create_key(ApiKeyCreateData(name=name, allowed_models=None, limits=[]))


async def _enable_api_key_auth(async_client) -> None:
    assert (await async_client.put("/api/settings", json={"apiKeyAuthEnabled": True})).status_code == 200


def _chat_body() -> dict:
    return {
        "model": "opencode-go/glm-5.3",
        "messages": [{"role": "user", "content": _PROMPT_CANARY}],
    }


def _responses_body() -> dict:
    return {"model": "opencode-go/glm-5.3", "input": _PROMPT_CANARY, "stream": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("route,body", [("/v1/chat/completions", _chat_body), ("/v1/responses", _responses_body)])
async def test_cleared_key_stops_the_prompt_leaving_the_process(
    async_client, sink, allow_loopback_base_url, trap_other_providers, route: str, body
):
    """The reported boundary, on both inbound protocols.

    After a successful clear the integration is enabled but has no credential.
    It must refuse locally rather than POST the user's prompt to the upstream.
    """

    await _configure(async_client, sink, api_key="sk-go-synthetic-key")
    await _configure(async_client, sink, api_key=None)  # confirmed clear
    await _enable_api_key_auth(async_client)
    key = await _api_key("go-key")

    response = await async_client.post(
        route,
        headers={"Authorization": f"Bearer {key.key}", "user-agent": "opencode/1.0"},
        json=body(),
    )

    assert sink.requests == [], f"unconfigured integration contacted the upstream: {sink.requests}"
    assert not sink.leaked_prompt
    assert trap_other_providers == [], f"prompt was rerouted to {trap_other_providers}"
    _assert_not_configured(response)


@pytest.mark.asyncio
@pytest.mark.parametrize("route,body", [("/v1/chat/completions", _chat_body), ("/v1/responses", _responses_body)])
async def test_never_configured_key_stops_the_prompt_leaving_the_process(
    async_client, sink, allow_loopback_base_url, trap_other_providers, route: str, body
):
    """Same boundary from the initial-missing-key direction, never having held one."""

    await _configure(async_client, sink, api_key=None)
    await _enable_api_key_auth(async_client)
    key = await _api_key("go-key")

    response = await async_client.post(
        route,
        headers={"Authorization": f"Bearer {key.key}", "user-agent": "opencode/1.0"},
        json=body(),
    )

    assert sink.requests == []
    assert not sink.leaked_prompt
    assert trap_other_providers == [], f"prompt was rerouted to {trap_other_providers}"
    _assert_not_configured(response)


@pytest.mark.asyncio
async def test_an_undecryptable_key_is_treated_as_absent(
    async_client, sink, allow_loopback_base_url, trap_other_providers, monkeypatch
):
    """A key we cannot read is not a key we may send a prompt alongside.

    Decryption failure yields ``api_key=None``; the request must fail closed the
    same way rather than going out unauthenticated.
    """

    await _configure(async_client, sink, api_key="sk-go-synthetic-key")

    from app.modules.proxy import opencode_go_sidecar_dispatch as dispatch

    monkeypatch.setattr(dispatch, "_decrypt_opencode_go_secret", lambda _encrypted: None)
    await _enable_api_key_auth(async_client)
    key = await _api_key("go-key")

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}", "user-agent": "opencode/1.0"},
        json=_chat_body(),
    )

    assert sink.requests == []
    assert not sink.leaked_prompt
    assert trap_other_providers == [], f"prompt was rerouted to {trap_other_providers}"
    _assert_not_configured(response)


@pytest.mark.asyncio
async def test_model_listing_does_not_contact_the_upstream_unconfigured(async_client, sink, allow_loopback_base_url):
    """``GET /v1/models`` must not poll a subscription it has no credential for.

    Nothing is advertised either: a model cannot be served without a key, so
    listing it would promise a route that fails.
    """

    await _configure(async_client, sink, api_key=None)

    response = await async_client.get("/v1/models")

    assert response.status_code == 200
    assert sink.requests == []
    assert "glm-5.3" not in {item["id"] for item in response.json()["data"]}


@pytest.mark.asyncio
async def test_a_configured_key_still_reaches_the_upstream(async_client, sink, allow_loopback_base_url):
    """Control: the fail-closed guard must not break the configured path.

    Without this, a guard that simply refused everything would pass every other
    test in this file.
    """

    await _configure(async_client, sink, api_key="sk-go-synthetic-key")
    await _enable_api_key_auth(async_client)
    key = await _api_key("go-key")

    await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}", "user-agent": "opencode/1.0"},
        json=_chat_body(),
    )

    assert len(sink.requests) == 1
    assert sink.requests[0]["authorization"] == "Bearer sk-go-synthetic-key"
    assert json.loads(sink.requests[0]["body"] or "{}")["model"] == "glm-5.3"
