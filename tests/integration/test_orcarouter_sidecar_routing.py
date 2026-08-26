from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from sqlalchemy import select

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.orcarouter_sidecar import (
    OrcaRouterSidecarClient,
    OrcaRouterSidecarConfig,
    OrcaRouterSidecarError,
    OrcaRouterSidecarUnavailableError,
    reset_orcarouter_sidecar_client_cache,
)
from app.core.config.settings import get_settings
from app.core.openai.model_registry import ReasoningLevel, UpstreamModel, get_model_registry
from app.db.models import ApiKeyUsageReservation, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService, LimitRuleInput
from app.modules.proxy.cursor_chat_compat import CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class _FakeModel:
    id: str
    created: int | None = 123
    owned_by: str | None = "orcarouter"


class _FakeOrcaRouterClient:
    def __init__(self, config: OrcaRouterSidecarConfig) -> None:
        self.config = config
        self.chat_payloads: list[dict] = []
        self.stream_payloads: list[dict] = []
        self.models = [_FakeModel("orcarouter/auto")]
        self.chat_error: Exception | None = None
        self.stream_error: Exception | None = None
        self.stream_include_usage = True
        self.stream_context_error = False
        # OrcaRouter reports the billed amount as ``usage.cost_usd`` when the
        # request opted in via ``X-OrcaRouter-Include-Cost``. Set to None to
        # model an upstream that omitted it.
        self.billed_cost_usd: float | None = None

    async def list_models_cached(self):
        return self.models

    async def chat_completion(self, payload):
        self.chat_payloads.append(dict(payload))
        if self.chat_error is not None:
            raise self.chat_error
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        if self.billed_cost_usd is not None:
            usage["cost_usd"] = self.billed_cost_usd
        return {
            "id": "chatcmpl-orcarouter",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": usage,
        }

    def stream_chat_completion(self, payload):
        self.stream_payloads.append(dict(payload))
        return _FakeStreamContext(
            self.stream_error,
            include_usage=self.stream_include_usage,
            context_error=self.stream_context_error,
            billed_cost_usd=self.billed_cost_usd,
        )


class _FakeStreamContext:
    def __init__(
        self,
        error: Exception | None,
        *,
        include_usage: bool = True,
        context_error: bool = False,
        billed_cost_usd: float | None = None,
    ) -> None:
        self.error = error
        self.include_usage = include_usage
        self.context_error = context_error
        self.billed_cost_usd = billed_cost_usd

    async def __aenter__(self):
        if self.error is not None:
            raise self.error

        async def chunks():
            yield b'data: {"id":"chunk-1","object":"chat.completion.chunk","choices":[{"delta":{"content":"hi"}}]}\n\n'
            if self.context_error:
                yield (
                    b'data: {"error":{"code":"context_length_exceeded",'
                    b'"message":"Input token limit exceeded"}}\n\n'
                )
                yield b"data: [DONE]\n\n"
                return
            if self.include_usage:
                usage = {"prompt_tokens": 10, "completion_tokens": 5}
                if self.billed_cost_usd is not None:
                    usage["cost_usd"] = self.billed_cost_usd
                trailing = {
                    "id": "chunk-2",
                    "object": "chat.completion.chunk",
                    "choices": [],
                    "usage": usage,
                }
                yield f"data: {json.dumps(trailing)}\n\n".encode()
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
async def orcarouter_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_ORCAROUTER_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def fake_orcarouter(monkeypatch):
    config = OrcaRouterSidecarConfig(
        enabled=True,
        base_url="https://api.orcarouter.ai/v1",
        api_key="orcarouter-key",
        prefixes=(SidecarPrefix(prefix="orcarouter/", strip=False),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=("orcarouter/auto",),
    )
    client = _FakeOrcaRouterClient(config)

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_orcarouter_sidecar_config", load_config)
    monkeypatch.setattr("app.modules.proxy.api.OrcaRouterSidecarClient", lambda _config: client)
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
        return await service.create_key(
            ApiKeyCreateData(name=name, allowed_models=allowed_models, limits=limits or [])
        )


async def _reservation_statuses() -> list[str]:
    async with SessionLocal() as session:
        result = await session.execute(select(ApiKeyUsageReservation.status))
        return list(result.scalars().all())


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
async def test_orcarouter_non_stream_routes_to_sidecar_and_finalizes_reservation(
    async_client,
    orcarouter_enabled,
    fake_orcarouter,
):
    await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "orcarouter-key",
            "orcarouterSidecarModelPrefixes": ["orcarouter/"],
            "orcarouterSidecarFullModels": ["orcarouter/auto"],
        },
    )
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "orcarouter-key",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)],
    )

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": "orcarouter/auto", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "hi"
    assert fake_orcarouter.chat_payloads[0]["model"] == "orcarouter/auto"
    assert await _reservation_statuses() == ["finalized"]
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    sidecar_logs = [log for log in logs if log.source == "orcarouter_sidecar"]
    assert len(sidecar_logs) == 1
    assert sidecar_logs[0].model == "orcarouter/auto"


@pytest.mark.asyncio
async def test_orcarouter_model_list_merges_and_filters(async_client, orcarouter_enabled, fake_orcarouter):
    await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "orcarouter-key",
            "orcarouterSidecarModelPrefixes": ["orcarouter/"],
        },
    )
    await _enable_api_key_auth(async_client)
    registry = get_model_registry()
    await registry.update({"plus": [_make_upstream_model("gpt-5.4")]})
    key = await _create_api_key("models-key", allowed_models=["orcarouter/auto"])

    response = await async_client.get("/v1/models", headers={"Authorization": f"Bearer {key.key}"})

    assert response.status_code == 200
    data = response.json()["data"]
    ids = [item["id"] for item in data]
    assert "orcarouter/auto" in ids
    assert "gpt-5.4" not in ids

    sidecar_entry = next(item for item in data if item["id"] == "orcarouter/auto")
    # Clients (e.g. Cursor) read the advertised context window to trigger their
    # own compaction; sidecar models must expose it.
    assert sidecar_entry["context_length"] == 200_000
    assert sidecar_entry["capabilities"]["context_length"] == 200_000


@pytest.mark.asyncio
async def test_gpt_request_does_not_hit_orcarouter_sidecar(async_client, orcarouter_enabled, fake_orcarouter):
    await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "orcarouter-key",
            "orcarouterSidecarModelPrefixes": ["orcarouter/"],
        },
    )

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code in {502, 503}
    assert fake_orcarouter.chat_payloads == []
    assert fake_orcarouter.stream_payloads == []


@pytest.mark.asyncio
async def test_orcarouter_sidecar_unavailable_returns_503(async_client, orcarouter_enabled, fake_orcarouter):
    await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "orcarouter-key",
            "orcarouterSidecarModelPrefixes": ["orcarouter/"],
        },
    )
    fake_orcarouter.chat_error = OrcaRouterSidecarUnavailableError("upstream down")

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "orcarouter/auto", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "orcarouter_sidecar_unavailable"


@pytest.mark.asyncio
async def test_orcarouter_sidecar_cursor_stream_applies_usage_fallback(
    async_client,
    orcarouter_enabled,
    fake_orcarouter,
):
    await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "orcarouter-key",
            "orcarouterSidecarModelPrefixes": ["orcarouter/"],
        },
    )
    fake_orcarouter.stream_include_usage = False

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"User-Agent": "Cursor/1.0"},
        json={
            "model": "orcarouter/auto",
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
async def test_orcarouter_sidecar_cursor_stream_context_limit_returns_synthetic_usage(
    async_client,
    orcarouter_enabled,
    fake_orcarouter,
):
    await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "orcarouter-key",
            "orcarouterSidecarModelPrefixes": ["orcarouter/"],
        },
    )
    fake_orcarouter.stream_context_error = True

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"User-Agent": "Cursor/1.0"},
        json={
            "model": "orcarouter/auto",
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
async def test_orcarouter_sidecar_non_cursor_stream_does_not_apply_usage_fallback(
    async_client,
    orcarouter_enabled,
    fake_orcarouter,
):
    await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "orcarouter-key",
            "orcarouterSidecarModelPrefixes": ["orcarouter/"],
        },
    )
    fake_orcarouter.stream_include_usage = False

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "orcarouter/auto",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as response:
        body = await response.aread()

    assert response.status_code == 200
    assert _usage_chunks(_chat_sse_payloads(body)) == []
    assert body.rstrip().endswith(b"data: [DONE]")


@pytest.mark.asyncio
async def test_orcarouter_sidecar_alias_is_discoverable_and_routes(async_client, orcarouter_enabled, fake_orcarouter):
    await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "orcarouter-key",
            "orcarouterSidecarFullModels": ["orcarouter/auto"],
            "modelAliases": {
                "alias-deepseek": "orcarouter/auto",
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
    assert fake_orcarouter.chat_payloads
    assert fake_orcarouter.chat_payloads[0]["model"] == "orcarouter/auto"



@pytest.mark.asyncio
async def test_repeated_model_list_requests_reuse_the_orcarouter_models_cache(
    async_client,
    orcarouter_enabled,
    monkeypatch,
):
    """``GET /v1/models`` must not pay an upstream round trip on every call.

    ``list_models_cached`` keeps its TTL state on the client instance, so building
    a client inline per request made ``models_cache_ttl_seconds`` dead: each call
    blocked on a fresh HTTPS fetch for up to ``request_timeout_seconds``.
    """

    reset_orcarouter_sidecar_client_cache()
    config = OrcaRouterSidecarConfig(
        enabled=True,
        base_url="https://api.orcarouter.ai/v1",
        api_key="orcarouter-key",
        prefixes=(SidecarPrefix(prefix="orcarouter/", strip=False),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=("orcarouter/auto",),
    )
    upstream_fetches = 0

    async def _counting_list_models(_self):
        nonlocal upstream_fetches
        upstream_fetches += 1
        return [_FakeModel("orcarouter/auto")]

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_orcarouter_sidecar_config", load_config)
    monkeypatch.setattr(OrcaRouterSidecarClient, "list_models", _counting_list_models)

    try:
        await async_client.put(
            "/api/settings",
            json={
                "orcarouterSidecarEnabled": True,
                "orcarouterSidecarApiKey": "orcarouter-key",
                "orcarouterSidecarModelPrefixes": ["orcarouter/"],
                "orcarouterSidecarFullModels": ["orcarouter/auto"],
            },
        )
        await _enable_api_key_auth(async_client)
        key = await _create_api_key("models-cache-key", allowed_models=["orcarouter/auto"])
        headers = {"Authorization": f"Bearer {key.key}"}

        for _ in range(3):
            response = await async_client.get("/v1/models", headers=headers)
            assert response.status_code == 200
            assert "orcarouter/auto" in [item["id"] for item in response.json()["data"]]

        assert upstream_fetches == 1
    finally:
        reset_orcarouter_sidecar_client_cache()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_orcarouter_billed_cost_reaches_the_request_log(
    async_client,
    orcarouter_enabled,
    fake_orcarouter,
    stream,
):
    """The authoritative billed figure must be stored, never re-derived.

    OrcaRouter's amount folds in tiered pricing, peak multipliers, cache ratios
    and minimum-quota rounding, so list prices are not a substitute
    (docs.orcarouter.ai/operations/per-request-cost).
    """

    fake_orcarouter.billed_cost_usd = 0.00846
    await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "orcarouter-key",
            "orcarouterSidecarModelPrefixes": ["orcarouter/"],
        },
    )
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("billed-cost-key")

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={
            "model": "orcarouter/auto",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": stream,
        },
    )
    assert response.status_code == 200
    if stream:
        # Streaming carries cost on the trailing usage frame, which the sidecar
        # already requests via stream_options.include_usage.
        assert _usage_chunks(_chat_sse_payloads(response.content))

    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    sidecar_logs = [log for log in logs if log.source == "orcarouter_sidecar"]
    assert len(sidecar_logs) == 1
    assert sidecar_logs[0].cost_usd == pytest.approx(0.00846)


@pytest.mark.asyncio
async def test_orcarouter_request_log_cost_stays_null_when_upstream_omits_it(
    async_client,
    orcarouter_enabled,
    fake_orcarouter,
):
    """Absence means "no number to report", never "free" - so never invent one."""

    fake_orcarouter.billed_cost_usd = None
    await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "orcarouter-key",
            "orcarouterSidecarModelPrefixes": ["orcarouter/"],
        },
    )
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("no-billed-cost-key")

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": "orcarouter/auto", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200

    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    sidecar_logs = [log for log in logs if log.source == "orcarouter_sidecar"]
    assert len(sidecar_logs) == 1
    assert sidecar_logs[0].cost_usd is None


# Not a real credential: a synthetic string shaped like an OrcaRouter key so the
# assertions below prove the sanitizer removed it.
_FAKE_ORCAROUTER_KEY = "sk-orca-NOTAREALKEY000000000"


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "upstream_message",
    [
        "Unauthorized for Authorization: Bearer {key}",
        'upstream echoed {{"authorization":"Bearer {key}"}}',
        "Invalid API key: {key}",
    ],
)
async def test_orcarouter_chat_error_never_persists_the_bearer_token(
    async_client,
    orcarouter_enabled,
    fake_orcarouter,
    stream,
    upstream_message,
):
    """An upstream that echoes the Authorization header must not leak the key.

    Chat dispatch persists the upstream text to ``request_logs.error_message``,
    which is durable and rendered (with a copy button) by the dashboard request
    drawer, and relays it to the calling API key. A 500 keeps the passthrough
    path live - 401/403 are already remapped by ``client_facing_sidecar_error``.
    """

    leaked = upstream_message.format(key=_FAKE_ORCAROUTER_KEY)
    error = OrcaRouterSidecarError(500, leaked, body={"error": {"message": leaked}})
    if stream:
        fake_orcarouter.stream_error = error
    else:
        fake_orcarouter.chat_error = error

    await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": _FAKE_ORCAROUTER_KEY,
            "orcarouterSidecarModelPrefixes": ["orcarouter/"],
        },
    )
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(f"leak-key-{stream}-{abs(hash(upstream_message))}")

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={
            "model": "orcarouter/auto",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": stream,
        },
    )

    assert _FAKE_ORCAROUTER_KEY.encode() not in response.content

    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    sidecar_logs = [log for log in logs if log.source == "orcarouter_sidecar"]
    assert len(sidecar_logs) == 1
    persisted = sidecar_logs[0].error_message or ""
    assert _FAKE_ORCAROUTER_KEY not in persisted
    assert "[redacted]" in persisted
