"""An OrcaRouter or OpenRouter integration without an API key sends the prompt nowhere.

Kody on PR #71: verify the provider has a usable credential before building or
sending the request, and refuse it explicitly rather than treating it as an
ordinary failover target.

Reproduced before the fix. Enabled with no key, both integrations POSTed the
caller's prompt with no ``Authorization`` header, the upstream answered 401, and
the client got a generic ``sidecar_upstream_unavailable`` 503. Inside a pool the
401 was a retryable failover, so the prompt went to every keyless provider in
turn and each one was put on a 60-second cooldown for a failure that had nothing
to do with its health.

The disclosure is the request body, and it happens on the way out: the 401
coming back proves nothing about what the upstream already received. The same
boundary for OpenCode Go is ``test_opencode_go_unconfigured_egress.py``; this
file drives the real ASGI app against loopback sinks that record what arrives,
with synthetic prompt text and no real credential or upstream.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from sqlalchemy import select

from app.core.config.settings import get_settings
from app.db.models import ApiKeyUsageReservation, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService, LimitRuleInput
from app.modules.proxy.alias_pool_attempts import POOL_ATTEMPTS_HEADER, get_alias_pool_cooldowns

pytestmark = pytest.mark.integration

#: Distinctive, so its presence in a captured body is unambiguous.
_PROMPT_CANARY = "SYNTHETIC-PROMPT-CANARY-must-not-leave-the-process"

ORCA_MODEL = "orcarouter/z-ai/glm-5.3"
OPENROUTER_MODEL = "z-ai/glm-5.3"
ALIAS = "pooled/glm-5.3"


class _RecordingSink:
    """A loopback upstream that records every request and answers like a real one.

    With a key it serves a chat completion (a streamed one when asked), so a
    configured integration is exercised end to end. Without a key it answers 401
    the way OrcaRouter and OpenRouter do.
    """

    def __init__(self) -> None:
        self.requests: list[dict[str, str | None]] = []
        sink = self

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0) or 0)
                body = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
                authorization = self.headers.get("Authorization")
                sink.requests.append(
                    {"method": "POST", "path": self.path, "authorization": authorization, "body": body}
                )
                if not authorization:
                    self._send(401, "application/json", b'{"error":{"message":"Missing API key","code":401}}')
                    return
                request = json.loads(body or "{}")
                if request.get("stream"):
                    self._send(
                        200,
                        "text/event-stream",
                        b'data: {"id":"c","object":"chat.completion.chunk","choices":[{"delta":{"content":"hi"}}]}\n\n'
                        b'data: {"id":"c","object":"chat.completion.chunk","choices":[],'
                        b'"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n'
                        b"data: [DONE]\n\n",
                    )
                    return
                completion = {
                    "id": "c",
                    "object": "chat.completion",
                    "model": request.get("model"),
                    "choices": [
                        {"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                }
                self._send(200, "application/json", json.dumps(completion).encode())

            def do_GET(self) -> None:
                sink.requests.append(
                    {
                        "method": "GET",
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "body": "",
                    }
                )
                self._send(200, "application/json", b'{"data":[]}')

            def _send(self, status: int, content_type: str, payload: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}/v1"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> _RecordingSink:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()

    @property
    def chat_requests(self) -> list[dict[str, str | None]]:
        return [entry for entry in self.requests if entry["method"] == "POST"]

    @property
    def leaked_prompt(self) -> bool:
        return any(_PROMPT_CANARY in (entry["body"] or "") for entry in self.requests)


@pytest.fixture
def sinks(monkeypatch) -> Iterator[tuple[_RecordingSink, _RecordingSink]]:
    monkeypatch.setenv("CODEX_LB_ORCAROUTER_SIDECAR_ENABLED", "true")
    monkeypatch.setenv("CODEX_LB_OPENROUTER_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    get_alias_pool_cooldowns().clear()
    with _RecordingSink() as orcarouter, _RecordingSink() as openrouter:
        yield orcarouter, openrouter
    get_alias_pool_cooldowns().clear()
    get_settings.cache_clear()


@pytest.fixture
def trap_other_providers(monkeypatch) -> list[str]:
    """Fail loudly if a refused request is rerouted to any other provider.

    The sinks alone cannot prove this: on a test database with no Codex
    accounts a fall-through also yields 503, so "sinks empty + 503" is met both
    by a correct local refusal and by the prompt going to Codex instead.
    """

    import app.modules.proxy.api as proxy_api
    from app.modules.proxy.service import ProxyService

    tripped: list[str] = []

    def _trap(name: str):
        def _fail(*_args: object, **_kwargs: object):
            tripped.append(name)
            raise AssertionError(f"refused request reached {name}")

        return _fail

    for name in (
        "proxy_chat_to_sidecar",
        "proxy_chat_to_openai_compat",
        "proxy_chat_to_opencode_go",
        "proxy_chat_to_ollama",
        "proxy_chat_to_omniroute",
        "_select_chat_model_source",
    ):
        monkeypatch.setattr(proxy_api, name, _trap(name), raising=True)
    monkeypatch.setattr(ProxyService, "stream_responses", _trap("ProxyService.stream_responses"), raising=True)
    return tripped


async def _configure(
    async_client,
    orcarouter: _RecordingSink,
    openrouter: _RecordingSink,
    *,
    orcarouter_key: str | None,
    openrouter_key: str | None,
) -> None:
    body: dict[str, object] = {
        "orcarouterSidecarEnabled": True,
        "orcarouterSidecarBaseUrl": orcarouter.base_url,
        "orcarouterSidecarModelPrefixes": ["orcarouter/"],
        "openrouterSidecarEnabled": True,
        "openrouterSidecarBaseUrl": openrouter.base_url,
        "openrouterSidecarModelPrefixes": ["z-ai/"],
        "modelAliases": {ALIAS: {"targets": [ORCA_MODEL, OPENROUTER_MODEL]}},
    }
    for prefix, key in (("orcarouter", orcarouter_key), ("openrouter", openrouter_key)):
        if key is None:
            body[f"{prefix}SidecarClearApiKey"] = True
        else:
            body[f"{prefix}SidecarApiKey"] = key
    response = await async_client.put("/api/settings", json=body)
    assert response.status_code == 200, response.text


async def _limited_api_key(async_client):
    assert (await async_client.put("/api/settings", json={"apiKeyAuthEnabled": True})).status_code == 200
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        return await service.create_key(
            ApiKeyCreateData(
                name="limited",
                allowed_models=None,
                limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)],
            )
        )


async def _logs() -> list[RequestLog]:
    async with SessionLocal() as session:
        return list((await session.execute(select(RequestLog))).scalars().all())


async def _reservation_statuses() -> list[str]:
    async with SessionLocal() as session:
        return list((await session.execute(select(ApiKeyUsageReservation.status))).scalars().all())


def _chat_body(model: str, *, stream: bool) -> dict[str, object]:
    return {"model": model, "messages": [{"role": "user", "content": _PROMPT_CANARY}], "stream": stream}


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True], ids=["non_stream", "stream"])
@pytest.mark.parametrize(
    ("model", "provider", "source"),
    [
        (ORCA_MODEL, "orcarouter", "orcarouter_sidecar"),
        (OPENROUTER_MODEL, "openrouter", "openrouter_sidecar"),
    ],
    ids=["orcarouter", "openrouter"],
)
async def test_a_keyless_integration_refuses_locally(
    async_client, sinks, trap_other_providers, model: str, provider: str, source: str, stream: bool
):
    """The reported boundary, for a model routed straight to the integration."""

    orcarouter, openrouter = sinks
    await _configure(async_client, orcarouter, openrouter, orcarouter_key=None, openrouter_key=None)
    key = await _limited_api_key(async_client)

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json=_chat_body(model, stream=stream),
    )

    assert orcarouter.requests == [] and openrouter.requests == [], "a keyless integration contacted its upstream"
    assert not orcarouter.leaked_prompt and not openrouter.leaked_prompt
    assert trap_other_providers == [], f"prompt was rerouted to {trap_other_providers}"
    # The integration's own refusal, not the generic upstream-401 remap: the
    # operator can see which integration is missing its key.
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == f"{provider}_not_configured"
    assert response.headers["retry-after"] == "60"
    [log] = await _logs()
    assert (log.source, log.model, log.status, log.error_code) == (source, model, "error", f"{provider}_not_configured")
    assert log.cost_usd is None and log.price_status is None
    # The reservation is handed back: nothing was sent, so nothing is charged.
    assert await _reservation_statuses() == ["released"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True], ids=["non_stream", "stream"])
async def test_a_pool_skips_a_keyless_target_without_sending_it_the_prompt(
    async_client, sinks, trap_other_providers, stream: bool
):
    """The pool form: skip the keyless target, serve from the next, cool nothing."""

    orcarouter, openrouter = sinks
    await _configure(async_client, orcarouter, openrouter, orcarouter_key=None, openrouter_key="sk-or-synthetic")
    key = await _limited_api_key(async_client)

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json=_chat_body(ALIAS, stream=stream),
    )

    assert response.status_code == 200, response.text
    assert orcarouter.requests == [] and not orcarouter.leaked_prompt
    assert [entry["authorization"] for entry in openrouter.chat_requests] == ["Bearer sk-or-synthetic"]
    assert trap_other_providers == []
    # Attempts count targets the request was sent to. The skipped target was
    # never contacted, so it is neither an attempt nor put on a cooldown: a
    # missing key says nothing about OrcaRouter's health.
    assert response.headers[POOL_ATTEMPTS_HEADER] == "1"
    assert get_alias_pool_cooldowns().cooldown_for(ORCA_MODEL) is None
    [log] = await _logs()
    assert (log.source, log.model, log.upstream_model, log.pool_attempts, log.status) == (
        "openrouter_sidecar",
        ALIAS,
        OPENROUTER_MODEL,
        1,
        "success",
    )
    assert await _reservation_statuses() == ["finalized"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True], ids=["non_stream", "stream"])
async def test_a_pool_with_no_keyed_target_refuses_without_contacting_anyone(
    async_client, sinks, trap_other_providers, stream: bool
):
    orcarouter, openrouter = sinks
    await _configure(async_client, orcarouter, openrouter, orcarouter_key=None, openrouter_key=None)
    key = await _limited_api_key(async_client)

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json=_chat_body(ALIAS, stream=stream),
    )

    assert orcarouter.requests == [] and openrouter.requests == []
    assert trap_other_providers == []
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "alias_pool_unavailable"
    assert response.headers["retry-after"] == "60"
    assert response.headers[POOL_ATTEMPTS_HEADER] == "0"
    assert get_alias_pool_cooldowns().cooldown_for(ORCA_MODEL) is None
    assert get_alias_pool_cooldowns().cooldown_for(OPENROUTER_MODEL) is None
    assert await _reservation_statuses() == ["released"]


@pytest.mark.asyncio
async def test_an_undecryptable_key_is_treated_as_absent(async_client, sinks, trap_other_providers, monkeypatch):
    """A key we cannot read is not a key we may send a prompt alongside."""

    from app.modules.proxy import orcarouter_sidecar_dispatch

    orcarouter, openrouter = sinks
    await _configure(async_client, orcarouter, openrouter, orcarouter_key="sk-orca-synthetic", openrouter_key=None)
    monkeypatch.setattr(orcarouter_sidecar_dispatch, "_decrypt_orcarouter_secret", lambda _encrypted: None)

    response = await async_client.post("/v1/chat/completions", json=_chat_body(ORCA_MODEL, stream=False))

    assert orcarouter.requests == [] and not orcarouter.leaked_prompt
    assert trap_other_providers == []
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "orcarouter_not_configured"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "provider"),
    [(ORCA_MODEL, "orcarouter"), (OPENROUTER_MODEL, "openrouter")],
    ids=["orcarouter", "openrouter"],
)
async def test_a_configured_key_still_reaches_the_upstream(async_client, sinks, model: str, provider: str):
    """Control: without it, a gate that refused everything would pass every test above."""

    orcarouter, openrouter = sinks
    await _configure(
        async_client, orcarouter, openrouter, orcarouter_key="sk-orca-synthetic", openrouter_key="sk-or-synthetic"
    )
    sink, key = (orcarouter, "sk-orca-synthetic") if provider == "orcarouter" else (openrouter, "sk-or-synthetic")

    response = await async_client.post("/v1/chat/completions", json=_chat_body(model, stream=False))

    assert response.status_code == 200, response.text
    assert [entry["authorization"] for entry in sink.chat_requests] == [f"Bearer {key}"]
    assert sink.leaked_prompt  # the configured path does send the prompt, to the right place
