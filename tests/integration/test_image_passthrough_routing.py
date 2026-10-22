"""Images reach the provider that owns the model, unchanged.

codex-lb routes; it does not judge image support. Every test sends the same
image on both inbound APIs and checks the owning provider received the exact
URL string, that a provider's refusal comes back unchanged without a second
provider being tried, and that a model nobody owns is a plain
``model_not_found`` instead of a Codex account error.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import app.modules.proxy.service as proxy_module
from app.core.clients.claude_sidecar import ClaudeSidecarConfig, ClaudeSidecarError, SidecarPrefix
from app.core.clients.openai_compat_sidecar import OpenAICompatSidecarConfig, OpenAICompatSidecarError
from app.core.clients.openrouter_sidecar import OpenRouterSidecarConfig, OpenRouterSidecarError
from app.core.config.settings import get_settings
from app.core.openai.model_registry import ReasoningLevel, UpstreamModel, get_model_registry
from app.db.models import ApiKeyUsageReservation
from app.db.session import SessionLocal

pytestmark = pytest.mark.integration

# A real 16x16 PNG, and a remote image, as clients send them.
PNG_DATA_URL = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAFklEQVR42mM4ISdHEmIY1TCqYfhqAADk"
    "YgQQ6ZuA8QAAAABJRU5ErkJggg=="
)
HTTPS_URL = "https://upload.wikimedia.org/wikipedia/commons/4/47/PNG_transparency_demonstration_1.png"
IMAGES = pytest.mark.parametrize("image", [PNG_DATA_URL, HTTPS_URL], ids=["data-url", "https-url"])

NVIDIA_ENDPOINT_ID = "5ccdbaa3-9245-4bf2-b763-2d17aabb055e"
NVIDIA_MODEL = "nvidia/nemotron-3.5-content-safety"
OPENROUTER_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
CLAUDE_MODEL = "claude-sonnet-4-5-20250929"
CODEX_MODEL = "gpt-5.4"
UNOWNED_MODEL = "nvidia/nemotron-3.5-content-safety:free"

NO_IMAGE_ENDPOINTS = "No endpoints found that support image input"


@dataclass(frozen=True, slots=True)
class _FakeModel:
    id: str
    created: int | None = 123
    owned_by: str | None = None
    raw: dict | None = None


class _FakeChatProvider:
    """Records every chat body a provider client is asked to send."""

    def __init__(self, name: str, model: str) -> None:
        self.name = name
        self.models = [_FakeModel(model)]
        self.config: object | None = None
        self.payloads: list[dict] = []
        self.error: Exception | None = None

    async def list_models_cached(self):
        return self.models

    async def chat_completion(self, payload):
        self.payloads.append(json.loads(json.dumps(payload)))
        if self.error is not None:
            raise self.error
        return {
            "id": f"chatcmpl-{self.name}",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "red"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
        }

    def stream_chat_completion(self, payload):
        self.payloads.append(json.loads(json.dumps(payload)))
        return _FakeStream(self.error)


class _FakeStream:
    def __init__(self, error: Exception | None) -> None:
        self.error = error

    async def __aenter__(self):
        if self.error is not None:
            raise self.error

        async def chunks():
            yield b'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"delta":{"content":"red"}}]}\n\n'
            yield (
                b'data: {"id":"c2","object":"chat.completion.chunk","choices":[],'
                b'"usage":{"prompt_tokens":10,"completion_tokens":1}}\n\n'
            )
            yield b"data: [DONE]\n\n"

        return chunks()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@dataclass
class _Upstreams:
    nvidia: _FakeChatProvider
    openrouter: _FakeChatProvider
    claude: _FakeChatProvider
    codex_payloads: list[dict]

    def calls(self) -> dict[str, int]:
        return {
            "nvidia": len(self.nvidia.payloads),
            "openrouter": len(self.openrouter.payloads),
            "claude": len(self.claude.payloads),
            "codex": len(self.codex_payloads),
        }


@pytest.fixture
def upstreams(monkeypatch) -> _Upstreams:
    nvidia_config = OpenAICompatSidecarConfig(
        endpoint_id=NVIDIA_ENDPOINT_ID,
        name="NVIDIA",
        enabled=True,
        base_url="https://integrate.api.nvidia.com/v1",
        api_key="nvidia-key",
        prefixes=(),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=(NVIDIA_MODEL,),
    )
    openrouter_config = OpenRouterSidecarConfig(
        enabled=True,
        base_url="https://openrouter.ai/api/v1",
        api_key="openrouter-key",
        prefixes=(),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=(OPENROUTER_MODEL,),
    )
    claude_config = ClaudeSidecarConfig(
        enabled=True,
        base_url="http://127.0.0.1:8317",
        api_key="sidecar-key",
        prefixes=(SidecarPrefix(prefix="claude", strip=False),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=(CLAUDE_MODEL,),
    )
    nvidia = _FakeChatProvider("nvidia", NVIDIA_MODEL)
    openrouter = _FakeChatProvider("openrouter", OPENROUTER_MODEL)
    claude = _FakeChatProvider("claude", CLAUDE_MODEL)
    nvidia.config, openrouter.config, claude.config = nvidia_config, openrouter_config, claude_config

    async def load_nvidia():
        return (nvidia_config,)

    async def load_openrouter():
        return openrouter_config

    async def load_claude():
        return claude_config

    monkeypatch.setenv("CODEX_LB_CLAUDE_SIDECAR_ENABLED", "true")
    monkeypatch.setenv("CODEX_LB_OPENROUTER_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("app.modules.proxy.api.load_openai_compat_configs", load_nvidia)
    monkeypatch.setattr("app.modules.proxy.api.OpenAICompatSidecarClient", lambda _config: nvidia)
    monkeypatch.setattr("app.modules.proxy.api.get_openai_compat_sidecar_client", lambda _config: nvidia)
    monkeypatch.setattr("app.modules.proxy.api.load_openrouter_sidecar_config", load_openrouter)
    monkeypatch.setattr("app.modules.proxy.api.OpenRouterSidecarClient", lambda _config: openrouter)
    monkeypatch.setattr("app.modules.proxy.api.load_sidecar_config", load_claude)
    monkeypatch.setattr("app.modules.proxy.api.ClaudeSidecarClient", lambda _config: claude)

    async def _no_cliproxy_credential(body, **_kwargs):
        del body
        return None

    monkeypatch.setattr(
        "app.modules.proxy.claude_sidecar_dispatch.apply_cliproxy_account_route",
        _no_cliproxy_credential,
    )

    codex_payloads: list[dict] = []

    async def fake_codex(payload, headers, access_token, account_id, base_url=None, raise_for_status=False, **kwargs):
        del headers, access_token, account_id, base_url, raise_for_status, kwargs
        codex_payloads.append(payload.to_payload())
        yield 'data: {"type":"response.output_text.delta","delta":"red"}\n\n'
        yield (
            'data: {"type":"response.completed","response":{"id":"resp_codex","object":"response",'
            '"status":"completed","output":[{"type":"message","role":"assistant","content":'
            '[{"type":"output_text","text":"red"}]}]}}\n\n'
        )

    monkeypatch.setattr(proxy_module, "core_stream_responses", fake_codex)
    yield _Upstreams(nvidia=nvidia, openrouter=openrouter, claude=claude, codex_payloads=codex_payloads)
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client(_reset_db_state, upstreams):
    del _reset_db_state, upstreams
    from app.main import create_app

    app = create_app()

    async def _drain(response) -> None:
        del response
        service = getattr(app.state, "proxy_service", None)
        if service is not None and hasattr(service, "drain_persistence_tasks"):
            await service.drain_persistence_tasks(timeout_seconds=5)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        event_hooks={"response": [_drain]},
    ) as http:
        yield http


def _encode_jwt(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return f"header.{base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')}.sig"


async def _import_codex_account(http: AsyncClient) -> None:
    claims = {
        "email": "images@example.com",
        "chatgpt_account_id": "acc_images",
        "https://api.openai.com/auth": {"chatgpt_plan_type": "plus"},
    }
    auth = {
        "tokens": {
            "idToken": _encode_jwt(claims),
            "accessToken": "access-token",
            "refreshToken": "refresh-token",
            "accountId": "acc_images",
        }
    }
    files = {"auth_json": ("auth.json", json.dumps(auth), "application/json")}
    response = await http.post("/api/accounts/import", files=files)
    assert response.status_code == 200, response.text


def _upstream_model(slug: str) -> UpstreamModel:
    return UpstreamModel(
        slug=slug,
        display_name=slug,
        description=slug,
        context_window=128000,
        input_modalities=("text", "image"),
        supported_reasoning_levels=(ReasoningLevel(effort="medium", description="medium"),),
        default_reasoning_level="medium",
        supports_reasoning_summaries=False,
        support_verbosity=False,
        default_verbosity=None,
        prefer_websockets=False,
        supports_parallel_tool_calls=True,
        supported_in_api=True,
        minimal_client_version=None,
        priority=0,
        available_in_plans=frozenset({"plus"}),
        raw={},
    )


@pytest_asyncio.fixture
async def authoritative_codex_catalog():
    """Every Codex account has reported its catalog, which lists only gpt-5.4."""

    registry = get_model_registry()
    state = await registry.export_state()
    await registry.clear()
    served = _upstream_model(CODEX_MODEL)
    await registry.update(
        {"plus": [served]},
        per_account_results={"acct": ("plus", [served])},
        active_account_plans={"acct": "plus"},
    )
    snapshot = registry.get_snapshot()
    assert snapshot is not None and snapshot.account_catalogs_authoritative
    yield
    await registry.import_state(state, content_hash="restore-image-passthrough")


def _chat_body(model: str, image: str, *, stream: bool = False) -> dict:
    return {
        "model": model,
        "stream": stream,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Is this image safe? One word."},
                    {"type": "image_url", "image_url": {"url": image}},
                ],
            }
        ],
    }


def _responses_body(model: str, image: str, *, stream: bool = False) -> dict:
    return {
        "model": model,
        "stream": stream,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Is this image safe? One word."},
                    {"type": "input_image", "image_url": image},
                ],
            }
        ],
    }


async def _post(http: AsyncClient, path: str, body: dict):
    if not body.get("stream"):
        return await http.post(path, json=body)
    async with http.stream("POST", path, json=body) as response:
        await response.aread()
        return response


def _chat_image_parts(payload: dict) -> list[dict]:
    content = payload["messages"][-1]["content"]
    assert isinstance(content, list)
    return [part for part in content if part.get("type") == "image_url"]


def _codex_image_parts(payload: dict) -> list[dict]:
    parts: list[dict] = []
    for item in payload["input"]:
        content = item.get("content") if isinstance(item, dict) else None
        if isinstance(content, list):
            parts.extend(part for part in content if isinstance(part, dict) and part.get("type") == "input_image")
    return parts


def _only(provider: str) -> dict[str, int]:
    """Exactly one call, to ``provider``; nothing else was tried."""

    return {"nvidia": 0, "openrouter": 0, "claude": 0, "codex": 0} | {provider: 1}


_CHAT_PROVIDERS = pytest.mark.parametrize(
    ("provider", "model"),
    [("nvidia", NVIDIA_MODEL), ("openrouter", OPENROUTER_MODEL), ("claude", CLAUDE_MODEL)],
    ids=["openai-compat-nvidia", "openrouter", "claude-cliproxy"],
)
_STREAM = pytest.mark.parametrize("stream", [False, True], ids=["json", "sse"])


@pytest.mark.asyncio
@_CHAT_PROVIDERS
@IMAGES
@_STREAM
async def test_chat_image_reaches_owning_provider_unchanged(client, upstreams, provider, model, image, stream):
    response = await _post(client, "/v1/chat/completions", _chat_body(model, image, stream=stream))

    assert response.status_code == 200
    fake: _FakeChatProvider = getattr(upstreams, provider)
    assert len(fake.payloads) == 1
    assert _chat_image_parts(fake.payloads[0]) == [{"type": "image_url", "image_url": {"url": image}}]
    assert upstreams.calls() == _only(provider)


@pytest.mark.asyncio
@_CHAT_PROVIDERS
@IMAGES
@_STREAM
async def test_responses_image_reaches_owning_provider_unchanged(client, upstreams, provider, model, image, stream):
    response = await _post(client, "/v1/responses", _responses_body(model, image, stream=stream))

    assert response.status_code == 200
    fake: _FakeChatProvider = getattr(upstreams, provider)
    assert len(fake.payloads) == 1
    assert _chat_image_parts(fake.payloads[0]) == [{"type": "image_url", "image_url": {"url": image}}]
    assert upstreams.calls() == _only(provider)


@pytest.mark.asyncio
@IMAGES
@pytest.mark.parametrize("path", ["/v1/chat/completions", "/v1/responses"])
async def test_codex_image_reaches_codex_unchanged(client, upstreams, image, path):
    await _import_codex_account(client)
    body = (
        _chat_body(CODEX_MODEL, image, stream=True)
        if "chat" in path
        else _responses_body(CODEX_MODEL, image, stream=True)
    )

    response = await _post(client, path, body)

    assert response.status_code == 200
    assert len(upstreams.codex_payloads) == 1
    assert _codex_image_parts(upstreams.codex_payloads[0]) == [{"type": "input_image", "image_url": image}]
    assert upstreams.calls() == _only("codex")


_PROVIDER_REFUSALS = pytest.mark.parametrize(
    ("provider", "model", "error"),
    [
        (
            "openrouter",
            OPENROUTER_MODEL,
            OpenRouterSidecarError(
                404,
                NO_IMAGE_ENDPOINTS,
                body={"error": {"message": NO_IMAGE_ENDPOINTS, "code": 404}},
            ),
        ),
        (
            "nvidia",
            NVIDIA_MODEL,
            OpenAICompatSidecarError(
                400,
                "Model does not support image input",
                body={"error": {"message": "Model does not support image input", "type": "invalid_request_error"}},
            ),
        ),
        (
            "claude",
            CLAUDE_MODEL,
            ClaudeSidecarError(
                400,
                "Could not process image",
                body={"error": {"message": "Could not process image", "type": "invalid_request_error"}},
            ),
        ),
    ],
    ids=["openrouter-404", "openai-compat-400", "claude-400"],
)


@pytest.mark.asyncio
@_PROVIDER_REFUSALS
@pytest.mark.parametrize("path", ["/v1/chat/completions", "/v1/responses"])
async def test_provider_image_refusal_is_returned_without_fallback(client, upstreams, provider, model, error, path):
    await _import_codex_account(client)
    fake: _FakeChatProvider = getattr(upstreams, provider)
    fake.error = error
    body = _chat_body(model, PNG_DATA_URL) if "chat" in path else _responses_body(model, PNG_DATA_URL)

    response = await client.post(path, json=body)

    assert response.status_code == error.status_code
    assert response.json()["error"]["message"] == error.message
    assert upstreams.calls() == _only(provider)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/v1/chat/completions", "/v1/responses"])
@pytest.mark.parametrize("model", [UNOWNED_MODEL, "nvidia/nemotron-3-content-safety"])
async def test_unowned_model_is_model_not_found_not_a_codex_error(
    client, upstreams, authoritative_codex_catalog, path, model
):
    await _import_codex_account(client)
    body = _chat_body(model, PNG_DATA_URL) if "chat" in path else _responses_body(model, PNG_DATA_URL)

    response = await client.post(path, json=body)

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "model_not_found"
    assert model in error["message"]
    assert upstreams.calls() == {"nvidia": 0, "openrouter": 0, "claude": 0, "codex": 0}
    async with SessionLocal() as session:
        assert (await session.execute(select(ApiKeyUsageReservation))).scalars().all() == []


@pytest.mark.asyncio
async def test_codex_catalog_model_still_routes_to_codex(client, upstreams, authoritative_codex_catalog):
    await _import_codex_account(client)

    response = await _post(client, "/v1/chat/completions", _chat_body(CODEX_MODEL, PNG_DATA_URL, stream=True))

    assert response.status_code == 200
    assert upstreams.calls() == {"nvidia": 0, "openrouter": 0, "claude": 0, "codex": 1}


@pytest.mark.asyncio
async def test_unowned_model_still_reaches_codex_before_catalogs_are_authoritative(client, upstreams):
    registry = get_model_registry()
    state = await registry.export_state()
    try:
        await registry.clear()
        await _import_codex_account(client)

        response = await _post(client, "/v1/chat/completions", _chat_body("gpt-legacy-slug", PNG_DATA_URL, stream=True))

        assert response.status_code == 200
        assert upstreams.calls() == {"nvidia": 0, "openrouter": 0, "claude": 0, "codex": 1}
    finally:
        await registry.import_state(state, content_hash="restore-image-passthrough")


@pytest.mark.asyncio
async def test_chat_tool_result_image_reaches_claude(client, upstreams):
    body = {
        "model": CLAUDE_MODEL,
        "messages": [
            {"role": "user", "content": "Take a screenshot."},
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "toolu_1", "name": "screenshot", "input": {}}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": [
                            {"type": "text", "text": "captured"},
                            {"type": "image_url", "image_url": {"url": PNG_DATA_URL}},
                        ],
                    }
                ],
            },
        ],
    }

    response = await client.post("/v1/chat/completions", json=body)

    assert response.status_code == 200
    tool_messages = [message for message in upstreams.claude.payloads[0]["messages"] if message["role"] == "tool"]
    assert tool_messages[0]["content"] == [
        {"type": "text", "text": "captured"},
        {"type": "image_url", "image_url": {"url": PNG_DATA_URL}},
    ]


@pytest.mark.asyncio
async def test_responses_tool_output_image_reaches_chat_provider(client, upstreams):
    body = {
        "model": NVIDIA_MODEL,
        "input": [
            {"role": "user", "content": "Take a screenshot."},
            {"type": "function_call", "call_id": "call_1", "name": "screenshot", "arguments": "{}"},
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": [
                    {"type": "input_text", "text": "captured"},
                    {"type": "input_image", "image_url": PNG_DATA_URL},
                ],
            },
        ],
    }

    response = await client.post("/v1/responses", json=body)

    assert response.status_code == 200
    tool_messages = [message for message in upstreams.nvidia.payloads[0]["messages"] if message["role"] == "tool"]
    assert tool_messages[0]["content"] == [
        {"type": "text", "text": "captured"},
        {"type": "image_url", "image_url": {"url": PNG_DATA_URL}},
    ]


@pytest.mark.asyncio
async def test_chat_tool_result_image_reaches_codex(client, upstreams):
    await _import_codex_account(client)
    body = {
        "model": CODEX_MODEL,
        "stream": True,
        "messages": [
            {"role": "user", "content": "Take a screenshot."},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "screenshot", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": [{"type": "image_url", "image_url": PNG_DATA_URL}]},
        ],
    }

    response = await _post(client, "/v1/chat/completions", body)

    assert response.status_code == 200
    outputs = [item for item in upstreams.codex_payloads[0]["input"] if item.get("type") == "function_call_output"]
    assert outputs[0]["output"] == [{"type": "input_image", "image_url": PNG_DATA_URL}]
