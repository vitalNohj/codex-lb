from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.openrouter_sidecar import (
    OpenRouterSidecarConfig,
    OpenRouterSidecarError,
    OpenRouterSidecarUnavailableError,
)
from app.core.config.settings import get_settings
from app.core.openai.model_registry import ReasoningLevel, UpstreamModel, get_model_registry
from app.db.models import ApiKeyLimit, ApiKeyUsageReservation, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService, LimitRuleInput
from app.modules.proxy.cursor_chat_compat import CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class _FakeModel:
    id: str
    created: int | None = 123
    owned_by: str | None = "openrouter"
    raw: dict | None = None


class _FakeOpenRouterClient:
    def __init__(self, config: OpenRouterSidecarConfig) -> None:
        self.config = config
        self.chat_payloads: list[dict] = []
        self.stream_payloads: list[dict] = []
        self.models = [_FakeModel("deepseek/deepseek-chat")]
        self.chat_error: Exception | None = None
        self.stream_error: Exception | None = None
        self.stream_include_usage = True
        self.stream_context_error = False

    async def list_models_cached(self):
        return self.models

    async def chat_completion(self, payload):
        self.chat_payloads.append(dict(payload))
        if self.chat_error is not None:
            raise self.chat_error
        return {
            "id": "chatcmpl-openrouter",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    def stream_chat_completion(self, payload):
        self.stream_payloads.append(dict(payload))
        return _FakeStreamContext(
            self.stream_error,
            include_usage=self.stream_include_usage,
            context_error=self.stream_context_error,
        )


class _FakeStreamContext:
    def __init__(
        self,
        error: Exception | None,
        *,
        include_usage: bool = True,
        context_error: bool = False,
    ) -> None:
        self.error = error
        self.include_usage = include_usage
        self.context_error = context_error

    async def __aenter__(self):
        if self.error is not None:
            raise self.error

        async def chunks():
            yield b'data: {"id":"chunk-1","object":"chat.completion.chunk","choices":[{"delta":{"content":"hi"}}]}\n\n'
            if self.context_error:
                yield (b'data: {"error":{"code":"context_length_exceeded","message":"Input token limit exceeded"}}\n\n')
                yield b"data: [DONE]\n\n"
                return
            if self.include_usage:
                yield (
                    b'data: {"id":"chunk-2","object":"chat.completion.chunk","choices":[],'
                    b'"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n'
                )
            yield b"data: [DONE]\n\n"

        return chunks()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def _make_upstream_model(slug: str) -> UpstreamModel:
    return UpstreamModel(
        slug=slug,
        display_name=slug,
        description=slug,
        context_window=128000,
        input_modalities=("text",),
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


@pytest.fixture
async def openrouter_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_OPENROUTER_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# Transports the catalog handler can reach, by the exact name it looks up:
# provider clients bound in ``app.modules.proxy.api`` plus the OrcaRouter
# factory the catalog path uses instead of the class (api.py:4076), and the
# native dispatch symbols. ``OpenRouterSidecarClient`` is absent because it is
# the transport this control expects to reach.
_CATALOG_CONTROL_REFUSED: tuple[str, ...] = (
    "ClaudeSidecarClient",
    "OpenAICompatSidecarClient",
    "get_openai_compat_sidecar_client",
    "OrcaRouterSidecarClient",
    "get_orcarouter_sidecar_client",
    "OmniRouteSidecarClient",
    "OllamaSidecarClient",
    "_source_chat_completion_response",
    "collect_chat_completion",
    "_probe_chat_stream_startup_error",
)


class _UnexpectedTransport(Exception):
    """A transport other than the expected OpenRouter fake was constructed."""


@pytest.fixture
def block_unexpected_transports(monkeypatch):
    """Refuse every reachable transport except this control's expected fake."""

    def _refuse(name: str):
        def _factory(*args, **kwargs):
            del args, kwargs
            raise _UnexpectedTransport(name)

        return _factory

    for name in _CATALOG_CONTROL_REFUSED:
        monkeypatch.setattr(f"app.modules.proxy.api.{name}", _refuse(name), raising=True)

    from app.modules.proxy.service import ProxyService

    monkeypatch.setattr(ProxyService, "stream_responses", _refuse("ProxyService.stream_responses"), raising=True)


@pytest_asyncio.fixture
async def lifespan_free_client(_reset_db_state, block_unexpected_transports, fake_openrouter, monkeypatch):
    """Real routers, middleware and temp database, without the app lifespan.

    Ordering is explicit: the guard and the expected fake are declared as
    parameters so both run first, and the fake is re-applied last so the guard
    can never leave the expected transport blocked.
    """
    del _reset_db_state, block_unexpected_transports
    import app.modules.proxy.api as proxy_api
    from app.main import create_app

    monkeypatch.setattr(
        "app.modules.proxy.api.OpenRouterSidecarClient",
        lambda _config: fake_openrouter,
        raising=True,
    )

    app = create_app()

    async def _drain_proxy_persistence(response) -> None:
        del response
        service = getattr(app.state, "proxy_service", None)
        if service is not None and hasattr(service, "drain_persistence_tasks"):
            await service.drain_persistence_tasks(timeout_seconds=5)

    assert proxy_api.__file__.startswith(str(Path(__file__).resolve().parents[2])), (
        f"app module resolved outside this task copy: {proxy_api.__file__}"
    )
    assert proxy_api.OpenRouterSidecarClient(fake_openrouter.config) is fake_openrouter
    for name in _CATALOG_CONTROL_REFUSED:
        with pytest.raises(_UnexpectedTransport):
            getattr(proxy_api, name)()

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        event_hooks={"response": [_drain_proxy_persistence]},
    ) as client:
        yield client


@pytest.fixture
async def fake_openrouter(monkeypatch):
    config = OpenRouterSidecarConfig(
        enabled=True,
        base_url="https://openrouter.ai/api/v1",
        api_key="openrouter-key",
        prefixes=(SidecarPrefix(prefix="deepseek/", strip=False),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=("deepseek/deepseek-chat",),
    )
    client = _FakeOpenRouterClient(config)

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_openrouter_sidecar_config", load_config)
    monkeypatch.setattr("app.modules.proxy.api.OpenRouterSidecarClient", lambda _config: client)
    return client


async def _enable_api_key_auth(async_client) -> None:
    response = await async_client.put("/api/settings", json={"apiKeyAuthEnabled": True})
    assert response.status_code == 200


async def _create_api_key(
    name: str,
    *,
    allowed_models: list[str] | None = None,
    limits: list[LimitRuleInput] | None = None,
):
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        return await service.create_key(ApiKeyCreateData(name=name, allowed_models=allowed_models, limits=limits or []))


async def _reservation_statuses() -> list[str]:
    async with SessionLocal() as session:
        result = await session.execute(select(ApiKeyUsageReservation.status))
        return list(result.scalars().all())


async def _limit_current_values() -> list[int]:
    """Durable reserved-quota counters, the resource a release actually returns.

    Reservation ``status`` alone does not prove the quota came back: settlement
    flips the row and adjusts ``api_key_limits.current_value`` in the same
    transaction, so the counter is the end-user-visible fact (how much of the
    key's allowance stays consumed) and the status is only its bookkeeping.
    """

    async with SessionLocal() as session:
        result = await session.execute(select(ApiKeyLimit.current_value))
        return list(result.scalars().all())


_TOTAL_TOKENS_LIMIT = LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)


def _context_length_error() -> OpenRouterSidecarError:
    return OpenRouterSidecarError(
        400,
        "This endpoint's maximum context length is 163840 tokens",
        body={"error": {"code": "context_length_exceeded", "message": "maximum context length"}},
    )


async def _configure_openrouter(async_client) -> None:
    response = await async_client.put(
        "/api/settings",
        json={
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
            "openrouterSidecarModelPrefixes": ["deepseek/"],
        },
    )
    assert response.status_code == 200, response.text


def _chat_sse_payloads(body: bytes | str) -> list[dict]:
    text = body.decode("utf-8") if isinstance(body, bytes) else body
    return [
        json.loads(line.removeprefix("data: "))
        for line in text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]


def _usage_chunks(payloads: list[dict]) -> list[dict]:
    return [payload for payload in payloads if payload.get("choices") == [] and "usage" in payload]


@pytest.mark.asyncio
async def test_openrouter_non_stream_routes_to_sidecar_and_finalizes_reservation(
    async_client,
    openrouter_enabled,
    fake_openrouter,
):
    await async_client.put(
        "/api/settings",
        json={
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
            "openrouterSidecarModelPrefixes": ["deepseek/"],
            "openrouterSidecarFullModels": ["deepseek/deepseek-chat"],
        },
    )
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "openrouter-key",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)],
    )

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "hi"
    assert fake_openrouter.chat_payloads[0]["model"] == "deepseek/deepseek-chat"
    assert await _reservation_statuses() == ["finalized"]
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    sidecar_logs = [log for log in logs if log.source == "openrouter_sidecar"]
    assert len(sidecar_logs) == 1
    assert sidecar_logs[0].model == "deepseek/deepseek-chat"


@pytest.mark.asyncio
async def test_openrouter_model_list_merges_and_filters(lifespan_free_client, openrouter_enabled, fake_openrouter):
    # Without the lifespan no cache-invalidation poller is registered, so the
    # settings write below is an in-process cache clear plus the temp-DB commit.
    # Assert that precondition instead of assuming it.
    from app.core.cache.invalidation import get_cache_invalidation_poller

    assert get_cache_invalidation_poller() is None

    settings_response = await lifespan_free_client.put(
        "/api/settings",
        json={
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
            "openrouterSidecarModelPrefixes": ["deepseek/"],
        },
    )
    assert settings_response.status_code == 200, settings_response.text

    await _enable_api_key_auth(lifespan_free_client)
    registry = get_model_registry()
    await registry.update({"plus": [_make_upstream_model("gpt-5.4")]})
    key = await _create_api_key("models-key", allowed_models=["deepseek/deepseek-chat"])

    response = await lifespan_free_client.get("/v1/models", headers={"Authorization": f"Bearer {key.key}"})

    assert response.status_code == 200
    data = response.json()["data"]
    ids = [item["id"] for item in data]
    assert "deepseek/deepseek-chat" in ids
    assert "gpt-5.4" not in ids

    sidecar_entry = next(item for item in data if item["id"] == "deepseek/deepseek-chat")
    # Clients (e.g. Cursor) read the advertised context window to trigger their
    # own compaction; sidecar models must expose it.
    assert sidecar_entry["context_length"] == 200_000
    assert sidecar_entry["capabilities"]["context_length"] == 200_000


@pytest.mark.asyncio
async def test_openrouter_model_list_advertises_the_catalog_context_window(
    lifespan_free_client, openrouter_enabled, fake_openrouter, monkeypatch
):
    """The window OpenRouter's own catalog reports is the one ``/v1/models`` shows.

    OpenRouter publishes ``context_length`` (and ``top_provider.context_length``)
    per model; a model whose entry carries neither keeps the 200k default, and an
    operator ``model_context_window_overrides`` entry wins over both.
    """

    from app.core.config.settings import get_settings
    from app.modules.proxy import api as proxy_api_module

    fake_openrouter.config = replace(
        fake_openrouter.config,
        full_models=(
            "deepseek/deepseek-chat",
            "deepseek/deepseek-r2",
            "deepseek/deepseek-lite",
            "deepseek/deepseek-pin",
        ),
    )
    config = fake_openrouter.config

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_openrouter_sidecar_config", load_config)
    fake_openrouter.models = [
        _FakeModel("deepseek/deepseek-chat", raw={"id": "deepseek/deepseek-chat", "context_length": 163_840}),
        _FakeModel(
            "deepseek/deepseek-r2", raw={"id": "deepseek/deepseek-r2", "top_provider": {"context_length": 131_072}}
        ),
        _FakeModel("deepseek/deepseek-lite", raw={"id": "deepseek/deepseek-lite", "context_length": True}),
        _FakeModel("deepseek/deepseek-pin", raw={"id": "deepseek/deepseek-pin", "context_length": 64_000}),
    ]
    patched = get_settings().model_copy(update={"model_context_window_overrides": {"deepseek/deepseek-pin": 96_000}})
    monkeypatch.setattr(proxy_api_module, "get_settings", lambda: patched)

    response = await lifespan_free_client.get("/v1/models")

    assert response.status_code == 200
    entries = {item["id"]: item for item in response.json()["data"]}
    expected = {
        "deepseek/deepseek-chat": 163_840,
        "deepseek/deepseek-r2": 131_072,
        "deepseek/deepseek-lite": 200_000,
        "deepseek/deepseek-pin": 96_000,
    }
    for model_id, window in expected.items():
        entry = entries[model_id]
        assert entry["context_length"] == window, model_id
        assert entry["contextLength"] == window, model_id
        assert entry["capabilities"]["context_length"] == window, model_id


@pytest.mark.asyncio
async def test_gpt_request_does_not_hit_openrouter_sidecar(async_client, openrouter_enabled, fake_openrouter):
    await async_client.put(
        "/api/settings",
        json={
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
            "openrouterSidecarModelPrefixes": ["deepseek/"],
        },
    )

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code in {502, 503}
    assert fake_openrouter.chat_payloads == []
    assert fake_openrouter.stream_payloads == []


@pytest.mark.asyncio
async def test_openrouter_sidecar_unavailable_returns_503(async_client, openrouter_enabled, fake_openrouter):
    await async_client.put(
        "/api/settings",
        json={
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
            "openrouterSidecarModelPrefixes": ["deepseek/"],
        },
    )
    fake_openrouter.chat_error = OpenRouterSidecarUnavailableError("upstream down")

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "openrouter_sidecar_unavailable"


@pytest.mark.asyncio
async def test_openrouter_sidecar_cursor_stream_applies_usage_fallback(
    async_client,
    openrouter_enabled,
    fake_openrouter,
):
    await async_client.put(
        "/api/settings",
        json={
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
            "openrouterSidecarModelPrefixes": ["deepseek/"],
        },
    )
    fake_openrouter.stream_include_usage = False

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"User-Agent": "Cursor/1.0"},
        json={
            "model": "deepseek/deepseek-chat",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as response:
        body = await response.aread()

    assert response.status_code == 200
    usage_chunks = _usage_chunks(_chat_sse_payloads(body))
    assert len(usage_chunks) == 1
    usage = usage_chunks[0]["usage"]
    assert usage["prompt_tokens"] > 0
    assert usage["completion_tokens"] > 0
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
    assert body.rstrip().endswith(b"data: [DONE]")


@pytest.mark.asyncio
async def test_openrouter_sidecar_cursor_stream_context_limit_returns_synthetic_usage(
    async_client,
    openrouter_enabled,
    fake_openrouter,
):
    await async_client.put(
        "/api/settings",
        json={
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
            "openrouterSidecarModelPrefixes": ["deepseek/"],
        },
    )
    fake_openrouter.stream_context_error = True

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"User-Agent": "Cursor/1.0"},
        json={
            "model": "deepseek/deepseek-chat",
            "messages": [{"role": "user", "content": "too much context"}],
            "stream": True,
        },
    ) as response:
        body = await response.aread()

    assert response.status_code == 200
    assert b'"error"' not in body
    usage_chunks = _usage_chunks(_chat_sse_payloads(body))
    assert len(usage_chunks) == 1
    assert usage_chunks[0]["usage"] == {
        "prompt_tokens": CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS,
        "completion_tokens": 0,
        "total_tokens": CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS,
    }
    assert body.rstrip().endswith(b"data: [DONE]")


@pytest.mark.asyncio
async def test_cursor_context_limit_error_is_logged_as_success_and_releases_its_reservation(
    async_client,
    openrouter_enabled,
    fake_openrouter,
):
    """A synthetic success must not be recorded as an error, and must not charge.

    The client receives HTTP 200 with synthetic usage, so logging it as an error
    and finalizing its reservation would charge quota for a request that was
    never billed and would report a failure the caller never saw.

    The key carries a real limit so a reservation genuinely exists: admission
    skips the reservation ledger entirely for a key with no applicable limit
    (``openspec/changes/skip-empty-usage-reservations``), and asserting a
    release against a key that never reserved anything tests nothing about the
    release path.
    """

    await _configure_openrouter(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("cursor-context-limit-key", limits=[_TOTAL_TOKENS_LIMIT])
    fake_openrouter.chat_error = _context_length_error()

    assert await _limit_current_values() == [0]

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}", "User-Agent": "Cursor/1.0"},
        json={"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": "too much"}]},
    )

    assert response.status_code == 200
    assert response.json()["usage"]["prompt_tokens"] == CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS

    # The client saw a success, so nothing may record this as a failed request.
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    sidecar_logs = [log for log in logs if log.source == "openrouter_sidecar"]
    assert not [log for log in sidecar_logs if log.status == "error"]
    assert not [log for log in sidecar_logs if log.error_code == "openrouter_sidecar_error"]
    # Released, never finalized: the upstream refused the request, so there is no
    # spend to settle and the reserved quota must go back.
    assert await _reservation_statuses() == ["released"]
    # The real resource, not just the bookkeeping row: the whole reserved
    # allowance is available again, so the refused request ties up no capacity.
    assert await _limit_current_values() == [0]


@pytest.mark.asyncio
async def test_cursor_context_limit_stream_releases_its_reservation(
    async_client,
    openrouter_enabled,
    fake_openrouter,
):
    """The streaming context-limit path returns the reserved quota too.

    Streaming settles in the iterator's ``finally``, on a task detached from the
    response, so this asserts after the suite's persistence drain rather than
    sleeping on a wall clock.
    """

    await _configure_openrouter(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("cursor-context-limit-stream-key", limits=[_TOTAL_TOKENS_LIMIT])
    fake_openrouter.stream_context_error = True

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}", "User-Agent": "Cursor/1.0"},
        json={
            "model": "deepseek/deepseek-chat",
            "messages": [{"role": "user", "content": "too much"}],
            "stream": True,
        },
    ) as response:
        body = await response.aread()

    assert response.status_code == 200
    assert b'"error"' not in body
    assert await _reservation_statuses() == ["released"]
    assert await _limit_current_values() == [0]


@pytest.mark.asyncio
async def test_cursor_context_limit_with_limit_free_key_creates_no_reservation(
    async_client,
    openrouter_enabled,
    fake_openrouter,
):
    """A key with no applicable limit reserves nothing, so there is nothing to release.

    This is the admission contract from ``skip-empty-usage-reservations``, not a
    leak: no reservation row is created, so no quota is held and the absence of
    a ``released`` row is the correct outcome rather than a missing release.
    """

    await _configure_openrouter(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("cursor-context-limit-unlimited-key")
    fake_openrouter.chat_error = _context_length_error()

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}", "User-Agent": "Cursor/1.0"},
        json={"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": "too much"}]},
    )

    assert response.status_code == 200
    assert response.json()["usage"]["prompt_tokens"] == CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS
    assert await _reservation_statuses() == []
    assert await _limit_current_values() == []


@pytest.mark.asyncio
async def test_cursor_context_limit_release_does_not_touch_another_requests_reservation(
    async_client,
    openrouter_enabled,
    fake_openrouter,
):
    """The release returns this request's quota only.

    A context-limit refusal on one key must not hand back the allowance another
    key's successful request legitimately consumed.
    """

    await _configure_openrouter(async_client)
    await _enable_api_key_auth(async_client)
    billed_key = await _create_api_key("cursor-context-limit-bystander-key", limits=[_TOTAL_TOKENS_LIMIT])

    billed = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {billed_key.key}"},
        json={"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert billed.status_code == 200
    # The fake upstream reports 10 prompt + 5 completion tokens.
    assert await _limit_current_values() == [15]

    refused_key = await _create_api_key("cursor-context-limit-refused-key", limits=[_TOTAL_TOKENS_LIMIT])
    fake_openrouter.chat_error = _context_length_error()

    refused = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {refused_key.key}", "User-Agent": "Cursor/1.0"},
        json={"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": "too much"}]},
    )

    assert refused.status_code == 200
    assert sorted(await _reservation_statuses()) == ["finalized", "released"]
    # The bystander keeps its legitimate charge; only the refused request's
    # reservation goes back.
    assert sorted(await _limit_current_values()) == [0, 15]


@pytest.mark.asyncio
async def test_openrouter_sidecar_non_cursor_stream_does_not_apply_usage_fallback(
    async_client,
    openrouter_enabled,
    fake_openrouter,
):
    await async_client.put(
        "/api/settings",
        json={
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
            "openrouterSidecarModelPrefixes": ["deepseek/"],
        },
    )
    fake_openrouter.stream_include_usage = False

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "deepseek/deepseek-chat",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as response:
        body = await response.aread()

    assert response.status_code == 200
    assert _usage_chunks(_chat_sse_payloads(body)) == []
    assert body.rstrip().endswith(b"data: [DONE]")


@pytest.mark.asyncio
async def test_openrouter_sidecar_alias_is_discoverable_and_routes(async_client, openrouter_enabled, fake_openrouter):
    await async_client.put(
        "/api/settings",
        json={
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
            "openrouterSidecarFullModels": ["deepseek/deepseek-chat"],
            "modelAliases": {
                "alias-deepseek": "deepseek/deepseek-chat",
            },
        },
    )

    models_response = await async_client.get("/v1/models")
    assert models_response.status_code == 200
    ids = {item["id"] for item in models_response.json()["data"]}
    assert "alias-deepseek" in ids

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "alias-deepseek", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert fake_openrouter.chat_payloads
    assert fake_openrouter.chat_payloads[0]["model"] == "deepseek/deepseek-chat"
