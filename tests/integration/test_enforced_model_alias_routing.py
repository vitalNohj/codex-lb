"""Enforced models take the bare-request rule, aliases the pool-target rule.

Kody on PR #119: ``alias_resolved`` stayed true whenever the client asked for
an alias, even when an API key's ``enforced_model`` replaced that alias. An
enforced ``openrouter::foo`` was then resolved by the pool-target rule - which
trusts the ``<provider>::`` prefix - and reached OpenRouter's ``foo`` instead
of OrcaRouter's literal full model ``openrouter::foo``.

Both integrations here deliberately list models that make the two rules
disagree: OrcaRouter owns the literal full model ``openrouter::foo`` and
OpenRouter owns ``foo``, so the same string resolves to different providers
depending on which rule applies.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.openrouter_sidecar import OpenRouterSidecarConfig
from app.core.clients.orcarouter_sidecar import OrcaRouterSidecarConfig
from app.core.config.settings import get_settings
from app.db.models import ApiKeyUsageReservation, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService
from app.modules.proxy.alias_pool_attempts import POOL_ATTEMPTS_HEADER

pytestmark = pytest.mark.integration

ALIAS = "pooled/enforced"
#: OrcaRouter lists this string as a literal full model; OpenRouter owns ``foo``.
ENFORCED_MODEL = "openrouter::foo"
OPENROUTER_MODEL = "foo"


class _FakeSidecar:
    def __init__(self, config, *, completion_id: str) -> None:
        self.config = config
        self.chat_payloads: list[dict] = []
        self.stream_payloads: list[dict] = []
        self._completion_id = completion_id

    async def list_models_cached(self):
        return []

    async def chat_completion(self, payload):
        self.chat_payloads.append(dict(payload))
        return {
            "id": self._completion_id,
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    def stream_chat_completion(self, payload):
        self.stream_payloads.append(dict(payload))

        async def chunks():
            yield b'data: {"id":"c","object":"chat.completion.chunk","choices":[{"delta":{"content":"hi"}}]}\n\n'
            yield (
                b'data: {"id":"c","object":"chat.completion.chunk","choices":[],'
                b'"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n'
            )
            yield b"data: [DONE]\n\n"

        return chunks()

    @property
    def attempts(self) -> int:
        return len(self.chat_payloads) + len(self.stream_payloads)

    @property
    def sent_model(self) -> str:
        assert self.attempts == 1, "expected exactly one dispatched request"
        return (self.stream_payloads or self.chat_payloads)[0]["model"]


@pytest.fixture
async def providers_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_ORCAROUTER_SIDECAR_ENABLED", "true")
    monkeypatch.setenv("CODEX_LB_OPENROUTER_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
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
        full_models=(ENFORCED_MODEL,),
    )
    client = _FakeSidecar(config, completion_id="chatcmpl-orcarouter")

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
        full_models=(OPENROUTER_MODEL,),
    )
    client = _FakeSidecar(config, completion_id="chatcmpl-openrouter")

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_openrouter_sidecar_config", load_config)
    monkeypatch.setattr("app.modules.proxy.api.OpenRouterSidecarClient", lambda _config: client)
    return client


async def _configure(async_client) -> None:
    response = await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "orcarouter-key",
            "orcarouterSidecarModelPrefixes": ["orcarouter/"],
            "orcarouterSidecarFullModels": [ENFORCED_MODEL],
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
            "openrouterSidecarModelPrefixes": ["z-ai/"],
            "openrouterSidecarFullModels": [OPENROUTER_MODEL],
            "modelAliases": {ALIAS: {"targets": [ENFORCED_MODEL]}},
        },
    )
    assert response.status_code == 200, response.text


async def _enable_api_key_auth(async_client) -> None:
    response = await async_client.put("/api/settings", json={"apiKeyAuthEnabled": True})
    assert response.status_code == 200, response.text


async def _create_enforced_key():
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        return await service.create_key(
            ApiKeyCreateData(name="enforced", allowed_models=None, enforced_model=ENFORCED_MODEL)
        )


async def _sidecar_logs() -> list[RequestLog]:
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    return [log for log in logs if log.source in {"orcarouter_sidecar", "openrouter_sidecar"}]


async def _reservation_statuses() -> list[str]:
    async with SessionLocal() as session:
        result = await session.execute(select(ApiKeyUsageReservation.status))
        return list(result.scalars().all())


def _chat_request(model: str) -> dict:
    return {"model": model, "messages": [{"role": "user", "content": "hi"}]}


@pytest.mark.asyncio
async def test_enforced_model_routes_by_the_bare_rule_even_when_the_client_asks_for_an_alias(
    async_client, providers_enabled, fake_orcarouter, fake_openrouter
):
    """The reported bug: an enforced model must never ride the alias's rule.

    The key enforces ``openrouter::foo`` and the client sends the alias whose
    target is that same string. Enforcement replaces the alias, so the string
    resolves as a bare request: OrcaRouter's literal full model wins, not
    OpenRouter's ``foo`` that the pool-target rule would hand it to.
    """

    await _configure(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_enforced_key()

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json=_chat_request(ALIAS),
    )

    assert response.status_code == 200, response.text
    assert response.json()["choices"][0]["message"]["content"] == "hi"
    assert fake_openrouter.attempts == 0, "the enforced model must not resolve by the pool-target rule"
    assert fake_orcarouter.attempts == 1
    assert fake_orcarouter.sent_model == ENFORCED_MODEL
    assert response.headers.get(POOL_ATTEMPTS_HEADER, "0") == "0", "an enforced request is not a pool dispatch"
    [log] = await _sidecar_logs()
    # An enforced request is direct: the log records only what the client used.
    assert (log.source, log.model, log.upstream_model, log.status) == (
        "orcarouter_sidecar",
        ENFORCED_MODEL,
        None,
        "success",
    )


@pytest.mark.asyncio
async def test_single_target_alias_dispatches_by_the_pool_target_rule(
    async_client, providers_enabled, fake_orcarouter, fake_openrouter
):
    """The control: without enforcement the alias target keeps its own rule.

    The same string as the alias's stored target resolves by the pool-target
    rule - which names OpenRouter - even though OrcaRouter lists the literal
    full model. This is the documented distinction the fix above must not
    disturb.
    """

    await _configure(async_client)

    response = await async_client.post("/v1/chat/completions", json=_chat_request(ALIAS))

    assert response.status_code == 200, response.text
    assert fake_orcarouter.attempts == 0, "a pool target must not be shadowed by a literal full model elsewhere"
    assert fake_openrouter.attempts == 1
    assert fake_openrouter.sent_model == OPENROUTER_MODEL
    assert response.headers.get(POOL_ATTEMPTS_HEADER, "0") == "0", "a single-target rewrite is not a pool dispatch"
    [log] = await _sidecar_logs()
    # The log keys the alias and records the stored pool target that served it;
    # the wire model OpenRouter actually saw is asserted above.
    assert (log.source, log.model, log.upstream_model, log.status) == (
        "openrouter_sidecar",
        ALIAS,
        ENFORCED_MODEL,
        "success",
    )


@pytest.mark.asyncio
async def test_bare_enforced_model_request_routes_by_the_exact_match(
    async_client, providers_enabled, fake_orcarouter, fake_openrouter
):
    """Asking for the enforced model directly was never broken; pin it."""

    await _configure(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_enforced_key()

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json=_chat_request(ENFORCED_MODEL),
    )

    assert response.status_code == 200, response.text
    assert fake_openrouter.attempts == 0
    assert fake_orcarouter.attempts == 1
    assert fake_orcarouter.sent_model == ENFORCED_MODEL