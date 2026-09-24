"""Alias pool failover on ``POST /v1/chat/completions``.

Two fake sidecars stand in for OrcaRouter and OpenRouter. Each test configures
a pool alias whose first target is OrcaRouter and second is OpenRouter, then
shapes the OrcaRouter fake's failure to drive the loop. Assertions are made
against the client-visible response, the upstream payloads each fake saw, the
request-log row, and the API-key reservation state, because the feature's
contract is exactly those four things.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import pytest
from sqlalchemy import select

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.openrouter_sidecar import (
    OpenRouterSidecarConfig,
    OpenRouterSidecarError,
    OpenRouterSidecarUnavailableError,
)
from app.core.clients.orcarouter_sidecar import (
    OrcaRouterSidecarConfig,
    OrcaRouterSidecarError,
    OrcaRouterSidecarUnavailableError,
)
from app.core.config.settings import get_settings
from app.db.models import ApiKeyUsageReservation, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService, LimitRuleInput
from app.modules.proxy.alias_pool_attempts import (
    POOL_ATTEMPTS_HEADER,
    get_alias_pool_cooldowns,
    reset_alias_pool_cooldowns,
)
from app.modules.proxy.cursor_chat_compat import CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS

pytestmark = pytest.mark.integration

ALIAS = "pooled/glm-5.3"
ORCA_TARGET = "orcarouter/z-ai/glm-5.3"
OPENROUTER_TARGET = "z-ai/glm-5.3"


@dataclass(frozen=True, slots=True)
class _FakeModel:
    id: str
    created: int | None = 123
    owned_by: str | None = "fake"


class _FakeStreamContext:
    def __init__(self, error: Exception | None, *, context_error: bool = False) -> None:
        self.error = error
        self.context_error = context_error

    async def __aenter__(self):
        if self.error is not None:
            raise self.error

        async def chunks():
            yield b'data: {"id":"chunk-1","object":"chat.completion.chunk","choices":[{"delta":{"content":"hi"}}]}\n\n'
            if self.context_error:
                yield b'data: {"error":{"code":"context_length_exceeded","message":"Input token limit exceeded"}}\n\n'
                yield b"data: [DONE]\n\n"
                return
            yield (
                b'data: {"id":"chunk-2","object":"chat.completion.chunk","choices":[],'
                b'"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n'
            )
            yield b"data: [DONE]\n\n"

        return chunks()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeSidecar:
    """Shared shape of the OrcaRouter and OpenRouter fakes.

    ``error`` is raised by both the non-streaming call and the streaming open,
    so one setting drives both request shapes in the parametrized tests.
    """

    def __init__(self, config, *, model_id: str, completion_id: str) -> None:
        self.config = config
        self.chat_payloads: list[dict] = []
        self.stream_payloads: list[dict] = []
        self.models = [_FakeModel(model_id)]
        self.error: Exception | None = None
        self.stream_context_error = False
        self._completion_id = completion_id

    async def list_models_cached(self):
        return self.models

    async def chat_completion(self, payload):
        self.chat_payloads.append(dict(payload))
        if self.error is not None:
            raise self.error
        return {
            "id": self._completion_id,
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    def stream_chat_completion(self, payload):
        self.stream_payloads.append(dict(payload))
        return _FakeStreamContext(self.error, context_error=self.stream_context_error)

    @property
    def attempts(self) -> int:
        return len(self.chat_payloads) + len(self.stream_payloads)


@pytest.fixture
async def pool_providers_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_ORCAROUTER_SIDECAR_ENABLED", "true")
    monkeypatch.setenv("CODEX_LB_OPENROUTER_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    reset_alias_pool_cooldowns()
    yield
    reset_alias_pool_cooldowns()
    get_settings.cache_clear()


@pytest.fixture
async def fake_orcarouter(monkeypatch) -> _FakeSidecar:
    config = OrcaRouterSidecarConfig(
        enabled=True,
        base_url="https://api.orcarouter.ai/v1",
        api_key="orcarouter-key",
        prefixes=(SidecarPrefix(prefix="orcarouter/", strip=False),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=(),
    )
    client = _FakeSidecar(config, model_id=ORCA_TARGET, completion_id="chatcmpl-orcarouter")

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_orcarouter_sidecar_config", load_config)
    monkeypatch.setattr("app.modules.proxy.api.OrcaRouterSidecarClient", lambda _config: client)
    monkeypatch.setattr("app.modules.proxy.api.get_orcarouter_sidecar_client", lambda _config: client)
    return client


@pytest.fixture
async def fake_openrouter(monkeypatch) -> _FakeSidecar:
    config = OpenRouterSidecarConfig(
        enabled=True,
        base_url="https://openrouter.ai/api/v1",
        api_key="openrouter-key",
        prefixes=(SidecarPrefix(prefix="z-ai/", strip=False),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=(),
    )
    client = _FakeSidecar(config, model_id=OPENROUTER_TARGET, completion_id="chatcmpl-openrouter")

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_openrouter_sidecar_config", load_config)
    monkeypatch.setattr("app.modules.proxy.api.OpenRouterSidecarClient", lambda _config: client)
    return client


async def _configure_pool(async_client, *, targets: list[str] | None = None, alias: str = ALIAS) -> None:
    response = await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "orcarouter-key",
            "orcarouterSidecarModelPrefixes": ["orcarouter/"],
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
            "openrouterSidecarModelPrefixes": ["z-ai/"],
            "modelAliases": {alias: {"targets": targets or [ORCA_TARGET, OPENROUTER_TARGET]}},
        },
    )
    assert response.status_code == 200, response.text


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


async def _sidecar_logs() -> list[RequestLog]:
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    return [log for log in logs if log.source in {"orcarouter_sidecar", "openrouter_sidecar"}]


def _chat_request(*, stream: bool, model: str = ALIAS) -> dict:
    body: dict = {"model": model, "messages": [{"role": "user", "content": "hi"}]}
    if stream:
        body["stream"] = True
    return body


def _sse_payloads(body: bytes) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in body.decode("utf-8").splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]


def _assert_served_by(response, fake: _FakeSidecar, *, stream: bool) -> None:
    assert response.status_code == 200, response.text
    if stream:
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.content.rstrip().endswith(b"data: [DONE]")
        assert _sse_payloads(response.content)[0]["choices"][0]["delta"]["content"] == "hi"
    else:
        assert response.json()["choices"][0]["message"]["content"] == "hi"


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True], ids=["non_stream", "stream"])
async def test_pool_serves_from_first_target_when_it_succeeds(
    async_client, pool_providers_enabled, fake_orcarouter, fake_openrouter, stream
):
    await _configure_pool(async_client)

    response = await async_client.post("/v1/chat/completions", json=_chat_request(stream=stream))

    _assert_served_by(response, fake_orcarouter, stream=stream)
    assert response.headers[POOL_ATTEMPTS_HEADER] == "1"
    assert fake_orcarouter.attempts == 1
    assert fake_openrouter.attempts == 0
    sent = (fake_orcarouter.stream_payloads or fake_orcarouter.chat_payloads)[0]
    assert sent["model"] == ORCA_TARGET

    logs = await _sidecar_logs()
    assert len(logs) == 1
    assert logs[0].model == ALIAS
    assert logs[0].upstream_model == ORCA_TARGET
    assert logs[0].pool_attempts == 1
    assert logs[0].latency_queue_ms is None


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True], ids=["non_stream", "stream"])
@pytest.mark.parametrize(
    ("failure", "target_calls"),
    [
        pytest.param(
            OrcaRouterSidecarError(402, "Insufficient credits", body={"error": {"message": "no credit"}}),
            1,
            id="402",
        ),
        pytest.param(OrcaRouterSidecarError(429, "Rate limited", headers={"Retry-After": "7"}), 1, id="429"),
        # A provider failure (HTTP 500 or above, transport included) first gets
        # the target's own one-shot retry; the pool fails over once that fails.
        pytest.param(OrcaRouterSidecarError(503, "Upstream overloaded"), 2, id="503"),
        pytest.param(OrcaRouterSidecarUnavailableError("connect timeout"), 2, id="transport"),
    ],
)
async def test_pool_fails_over_to_second_target_on_retryable_failure(
    async_client, pool_providers_enabled, fake_orcarouter, fake_openrouter, stream, failure, target_calls
):
    await _configure_pool(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "pool-key",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)],
    )
    fake_orcarouter.error = failure

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json=_chat_request(stream=stream),
    )

    _assert_served_by(response, fake_openrouter, stream=stream)
    # Pool attempts count targets; the provider retry stays inside one attempt.
    assert response.headers[POOL_ATTEMPTS_HEADER] == "2"
    assert fake_orcarouter.attempts == target_calls
    assert fake_openrouter.attempts == 1
    sent = (fake_openrouter.stream_payloads or fake_openrouter.chat_payloads)[0]
    assert sent["model"] == OPENROUTER_TARGET

    # One reservation, taken against the alias, finalized once by the serving
    # attempt. The failed attempt left no log row of its own.
    assert await _reservation_statuses() == ["finalized"]
    logs = await _sidecar_logs()
    assert len(logs) == 1
    assert logs[0].source == "openrouter_sidecar"
    assert logs[0].status == "success"
    assert logs[0].model == ALIAS
    assert logs[0].upstream_model == OPENROUTER_TARGET
    assert logs[0].pool_attempts == 2
    assert logs[0].latency_queue_ms is not None and logs[0].latency_queue_ms >= 0

    health = get_alias_pool_cooldowns().health(ORCA_TARGET)
    assert health.state == "cooling"
    assert health.last_status == failure.status_code
    assert get_alias_pool_cooldowns().health(OPENROUTER_TARGET).state == "healthy"


@pytest.mark.asyncio
async def test_pool_cooldown_honours_retry_after_and_402_window(
    async_client, pool_providers_enabled, fake_orcarouter, fake_openrouter
):
    await _configure_pool(async_client)
    registry = get_alias_pool_cooldowns()

    fake_orcarouter.error = OrcaRouterSidecarError(429, "Rate limited", headers={"Retry-After": "7"})
    await async_client.post("/v1/chat/completions", json=_chat_request(stream=False))
    entry = registry.cooldown_for(ORCA_TARGET)
    assert entry is not None
    remaining = entry.until_monotonic - time.monotonic()
    assert 5 < remaining <= 7

    reset_alias_pool_cooldowns()
    fake_orcarouter.error = OrcaRouterSidecarError(402, "Insufficient credits")
    await async_client.post("/v1/chat/completions", json=_chat_request(stream=False))
    entry = registry.cooldown_for(ORCA_TARGET)
    assert entry is not None
    remaining = entry.until_monotonic - time.monotonic()
    assert 29 * 60 < remaining <= 30 * 60


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True], ids=["non_stream", "stream"])
async def test_pool_skips_cooling_target_and_clears_cooldown_on_success(
    async_client, pool_providers_enabled, fake_orcarouter, fake_openrouter, stream
):
    await _configure_pool(async_client)
    fake_orcarouter.error = OrcaRouterSidecarError(402, "Insufficient credits")

    first = await async_client.post("/v1/chat/completions", json=_chat_request(stream=stream))
    assert first.headers[POOL_ATTEMPTS_HEADER] == "2"
    assert fake_orcarouter.attempts == 1

    # While OrcaRouter is cooling the next request goes straight to OpenRouter:
    # one attempt, and OrcaRouter is not called again.
    second = await async_client.post("/v1/chat/completions", json=_chat_request(stream=stream))
    _assert_served_by(second, fake_openrouter, stream=stream)
    assert second.headers[POOL_ATTEMPTS_HEADER] == "1"
    assert fake_orcarouter.attempts == 1
    assert fake_openrouter.attempts == 2

    # Once the cooldown is gone and OrcaRouter is healthy again it is preferred.
    reset_alias_pool_cooldowns()
    fake_orcarouter.error = None
    third = await async_client.post("/v1/chat/completions", json=_chat_request(stream=stream))
    _assert_served_by(third, fake_orcarouter, stream=stream)
    assert third.headers[POOL_ATTEMPTS_HEADER] == "1"
    assert fake_orcarouter.attempts == 2
    assert get_alias_pool_cooldowns().health(ORCA_TARGET).state == "healthy"


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True], ids=["non_stream", "stream"])
async def test_pool_tries_soonest_to_expire_target_when_everything_is_cooling(
    async_client, pool_providers_enabled, fake_orcarouter, fake_openrouter, stream
):
    await _configure_pool(async_client)
    fake_orcarouter.error = OrcaRouterSidecarError(402, "Insufficient credits")  # 30 min
    fake_openrouter.error = OpenRouterSidecarError(503, "Overloaded")  # 60 s

    exhausted = await async_client.post("/v1/chat/completions", json=_chat_request(stream=stream))
    assert exhausted.status_code == 503
    assert exhausted.headers[POOL_ATTEMPTS_HEADER] == "2"
    # The 402 fails over at once; the 503 was retried once on OpenRouter first.
    assert fake_orcarouter.attempts == 1
    assert fake_openrouter.attempts == 2

    # Both cooling: OpenRouter (60 s) expires before OrcaRouter (30 min), so it
    # is attempted first; a cooldown alone never turns into a 503.
    fake_openrouter.error = None
    recovered = await async_client.post("/v1/chat/completions", json=_chat_request(stream=stream))
    _assert_served_by(recovered, fake_openrouter, stream=stream)
    assert recovered.headers[POOL_ATTEMPTS_HEADER] == "1"
    assert fake_orcarouter.attempts == 1
    assert fake_openrouter.attempts == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True], ids=["non_stream", "stream"])
async def test_pool_returns_non_retryable_error_without_trying_second_target(
    async_client, pool_providers_enabled, fake_orcarouter, fake_openrouter, stream
):
    await _configure_pool(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "pool-key",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)],
    )
    fake_orcarouter.error = OrcaRouterSidecarError(
        400, "Invalid request", body={"error": {"message": "Invalid request", "code": "invalid_request"}}
    )

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json=_chat_request(stream=stream),
    )

    # Open-before-commit: the streaming shape gets the same JSON 400 as the
    # non-streaming one instead of an error frame inside a 200 event stream.
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["message"] == "Invalid request"
    assert response.headers[POOL_ATTEMPTS_HEADER] == "1"
    assert fake_orcarouter.attempts == 1
    assert fake_openrouter.attempts == 0
    assert get_alias_pool_cooldowns().health(ORCA_TARGET).state == "healthy"
    assert await _reservation_statuses() == ["released"]

    logs = await _sidecar_logs()
    assert len(logs) == 1
    assert logs[0].status == "error"
    assert logs[0].model == ALIAS
    assert logs[0].upstream_model == ORCA_TARGET
    assert logs[0].pool_attempts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True], ids=["non_stream", "stream"])
async def test_pool_returns_last_error_and_attempt_count_when_every_target_fails(
    async_client, pool_providers_enabled, fake_orcarouter, fake_openrouter, stream
):
    await _configure_pool(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "pool-key",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)],
    )
    fake_orcarouter.error = OrcaRouterSidecarError(402, "Insufficient credits")
    fake_openrouter.error = OpenRouterSidecarError(
        429, "OpenRouter rate limited", body={"error": {"message": "OpenRouter rate limited"}}
    )

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json=_chat_request(stream=stream),
    )

    assert response.status_code == 429
    assert response.json()["error"]["message"] == "OpenRouter rate limited"
    assert response.headers[POOL_ATTEMPTS_HEADER] == "2"
    assert fake_orcarouter.attempts == 1
    assert fake_openrouter.attempts == 1
    assert get_alias_pool_cooldowns().health(ORCA_TARGET).state == "cooling"
    assert get_alias_pool_cooldowns().health(OPENROUTER_TARGET).state == "cooling"

    # The reservation is settled exactly once, by the attempt that ended the
    # request, and that attempt is the only log row.
    assert await _reservation_statuses() == ["released"]
    logs = await _sidecar_logs()
    assert len(logs) == 1
    assert logs[0].source == "openrouter_sidecar"
    assert logs[0].status == "error"
    assert logs[0].model == ALIAS
    assert logs[0].upstream_model == OPENROUTER_TARGET
    assert logs[0].pool_attempts == 2


@pytest.mark.asyncio
async def test_pool_transport_failure_on_last_target_renders_the_503(
    async_client, pool_providers_enabled, fake_orcarouter, fake_openrouter
):
    await _configure_pool(async_client)
    fake_orcarouter.error = OrcaRouterSidecarError(402, "Insufficient credits")
    fake_openrouter.error = OpenRouterSidecarUnavailableError("connect timeout")

    response = await async_client.post("/v1/chat/completions", json=_chat_request(stream=False))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "openrouter_sidecar_unavailable"
    assert response.headers[POOL_ATTEMPTS_HEADER] == "2"
    assert fake_orcarouter.attempts == 1
    assert fake_openrouter.attempts == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True], ids=["non_stream", "stream"])
async def test_pool_cursor_context_length_error_wins_over_failover(
    async_client, pool_providers_enabled, fake_orcarouter, fake_openrouter, stream
):
    await _configure_pool(async_client)
    fake_orcarouter.error = OrcaRouterSidecarError(
        400,
        "Input token limit exceeded",
        body={"error": {"code": "context_length_exceeded", "message": "Input token limit exceeded"}},
    )

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"User-Agent": "Cursor/1.0"},
        json=_chat_request(stream=stream),
    )

    assert response.status_code == 200
    assert fake_openrouter.attempts == 0
    # Another target would hit the same context limit: the synthetic completion
    # is the answer, and the client learns the real prompt size from it.
    assert response.json()["usage"]["prompt_tokens"] == CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS


@pytest.mark.asyncio
async def test_pool_skips_target_the_key_may_not_use(
    async_client, pool_providers_enabled, fake_orcarouter, fake_openrouter
):
    await _configure_pool(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("restricted", allowed_models=[ALIAS, OPENROUTER_TARGET])

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json=_chat_request(stream=False),
    )

    # The alias is allowed and OpenRouter's target is allowed, OrcaRouter's is
    # not: the loop never reaches OrcaRouter and the row still shows one attempt.
    assert response.status_code == 200
    assert response.headers[POOL_ATTEMPTS_HEADER] == "1"
    assert fake_orcarouter.attempts == 0
    assert fake_openrouter.attempts == 1


@pytest.mark.asyncio
async def test_pool_rejects_key_allowed_on_alias_but_no_target(
    async_client, pool_providers_enabled, fake_orcarouter, fake_openrouter
):
    await _configure_pool(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("alias-only", allowed_models=[ALIAS])

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json=_chat_request(stream=False),
    )

    assert response.status_code == 403
    assert fake_orcarouter.attempts == 0
    assert fake_openrouter.attempts == 0
    assert await _reservation_statuses() == []


@pytest.mark.asyncio
async def test_model_filtered_limit_keyed_on_the_alias_applies(
    async_client, pool_providers_enabled, fake_orcarouter, fake_openrouter
):
    await _configure_pool(async_client)
    await _enable_api_key_auth(async_client)
    # The fake bills 15 total tokens per request, so a 15-token weekly cap is
    # exhausted by exactly one completion.
    key = await _create_api_key(
        "alias-limited",
        limits=[
            LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=15, model_filter=ALIAS),
        ],
    )
    headers = {"Authorization": f"Bearer {key.key}"}

    first = await async_client.post("/v1/chat/completions", headers=headers, json=_chat_request(stream=False))
    assert first.status_code == 200
    second = await async_client.post("/v1/chat/completions", headers=headers, json=_chat_request(stream=False))
    assert second.status_code == 429
    assert fake_orcarouter.attempts == 1


@pytest.mark.asyncio
async def test_model_filtered_limit_keyed_on_a_target_does_not_apply_through_the_alias(
    async_client, pool_providers_enabled, fake_orcarouter, fake_openrouter
):
    await _configure_pool(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "target-limited",
        limits=[
            LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=15, model_filter=ORCA_TARGET),
        ],
    )
    headers = {"Authorization": f"Bearer {key.key}"}

    for _ in range(2):
        response = await async_client.post("/v1/chat/completions", headers=headers, json=_chat_request(stream=False))
        assert response.status_code == 200
    assert fake_orcarouter.attempts == 2


@pytest.mark.asyncio
async def test_single_target_alias_is_logged_under_the_alias_without_pool_columns(
    async_client, pool_providers_enabled, fake_orcarouter, fake_openrouter
):
    await _configure_pool(async_client, alias="custom_glm", targets=[ORCA_TARGET])

    response = await async_client.post("/v1/chat/completions", json=_chat_request(stream=False, model="custom_glm"))

    assert response.status_code == 200
    assert POOL_ATTEMPTS_HEADER not in response.headers
    assert fake_orcarouter.chat_payloads[0]["model"] == ORCA_TARGET
    logs = await _sidecar_logs()
    assert len(logs) == 1
    assert logs[0].model == "custom_glm"
    assert logs[0].upstream_model == ORCA_TARGET
    assert logs[0].pool_attempts is None


@pytest.mark.asyncio
async def test_unaliased_request_leaves_pool_columns_null(
    async_client, pool_providers_enabled, fake_orcarouter, fake_openrouter
):
    await _configure_pool(async_client)

    response = await async_client.post("/v1/chat/completions", json=_chat_request(stream=True, model=ORCA_TARGET))

    assert response.status_code == 200
    assert POOL_ATTEMPTS_HEADER not in response.headers
    logs = await _sidecar_logs()
    assert len(logs) == 1
    assert logs[0].model == ORCA_TARGET
    assert logs[0].upstream_model is None
    assert logs[0].pool_attempts is None


@pytest.mark.asyncio
async def test_alias_pools_health_reflects_cooling_target_and_prunes_removed_ones(
    async_client, pool_providers_enabled, fake_orcarouter, fake_openrouter
):
    await _configure_pool(async_client)
    fake_orcarouter.error = OrcaRouterSidecarError(402, "Insufficient credits")
    await async_client.post("/v1/chat/completions", json=_chat_request(stream=False))

    health = await async_client.get("/api/settings/alias-pools/health")
    assert health.status_code == 200
    pool = health.json()["aliases"][ALIAS]
    assert pool[ORCA_TARGET]["state"] == "cooling"
    assert pool[ORCA_TARGET]["lastStatus"] == 402
    assert pool[ORCA_TARGET]["lastError"] == "Insufficient credits"
    assert pool[ORCA_TARGET]["until"] is not None
    assert pool[OPENROUTER_TARGET] == {"state": "healthy", "until": None, "lastStatus": None, "lastError": None}

    # Dropping OrcaRouter from the pool removes its entry and its cooldown.
    await _configure_pool(async_client, targets=[OPENROUTER_TARGET])
    health = await async_client.get("/api/settings/alias-pools/health")
    assert health.json()["aliases"] == {
        ALIAS: {OPENROUTER_TARGET: {"state": "healthy", "until": None, "lastStatus": None, "lastError": None}}
    }
    assert get_alias_pool_cooldowns().cooldown_for(ORCA_TARGET) is None


@pytest.mark.asyncio
async def test_unaliased_streaming_upstream_error_is_a_json_error_before_any_sse_bytes(
    async_client, pool_providers_enabled, fake_orcarouter, fake_openrouter
):
    await _configure_pool(async_client)
    fake_orcarouter.error = OrcaRouterSidecarError(502, "Bad gateway", body={"error": {"message": "Bad gateway"}})

    response = await async_client.post("/v1/chat/completions", json=_chat_request(stream=True, model=ORCA_TARGET))

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["message"] == "Bad gateway"
    assert b"data:" not in response.content
