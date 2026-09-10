from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.ollama_sidecar import OllamaSidecarConfig
from app.core.config.settings import get_settings
from app.db.models import ApiKeyUsageReservation, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService, LimitRuleInput

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class _FakeModel:
    id: str
    created: int | None = 123
    owned_by: str | None = "ollama"


class _FakeOllamaClient:
    def __init__(self, config: OllamaSidecarConfig) -> None:
        self.config = config
        self.chat_payloads: list[dict] = []
        self.models = [
            _FakeModel("gpt-oss:120b-cloud"),
            _FakeModel("deepseek-v3.1:671b-cloud"),
        ]

    async def list_models_cached(self):
        return self.models

    async def chat_completion(self, payload):
        self.chat_payloads.append(dict(payload))
        return {
            "model": payload["model"],
            "message": {"role": "assistant", "content": "hi"},
            "done_reason": "stop",
            "prompt_eval_count": 10,
            "eval_count": 5,
        }


@pytest.fixture
async def ollama_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_OLLAMA_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# Transports the catalog handler can reach, by the exact name it looks up:
# provider clients bound in ``app.modules.proxy.api`` plus the OrcaRouter
# factory the catalog path uses instead of the class (api.py:4076), and the
# native dispatch symbols. ``OllamaSidecarClient`` is absent because it is the
# transport this control expects to reach.
_CATALOG_CONTROL_REFUSED: tuple[str, ...] = (
    "ClaudeSidecarClient",
    "OpenRouterSidecarClient",
    "OrcaRouterSidecarClient",
    "get_orcarouter_sidecar_client",
    "OmniRouteSidecarClient",
    "_source_chat_completion_response",
    "collect_chat_completion",
    "_probe_chat_stream_startup_error",
)


class _UnexpectedTransport(Exception):
    """A transport other than the expected Ollama fake was constructed."""


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
async def lifespan_free_client(_reset_db_state, block_unexpected_transports, fake_ollama, monkeypatch):
    """Real routers, middleware and temp database, without the app lifespan.

    Ordering is explicit: the guard and the expected fake are declared as
    parameters so both run first, and the fake is re-applied last so the guard
    can never leave the expected transport blocked.
    """
    del _reset_db_state, block_unexpected_transports
    import app.modules.proxy.api as proxy_api
    from app.main import create_app

    monkeypatch.setattr(
        "app.modules.proxy.api.OllamaSidecarClient",
        lambda _config: fake_ollama,
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
    assert proxy_api.OllamaSidecarClient(fake_ollama.config) is fake_ollama
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
async def fake_ollama(monkeypatch):
    config = OllamaSidecarConfig(
        enabled=True,
        base_url="https://ollama.com",
        api_key="ollama-key",
        prefixes=(SidecarPrefix(prefix="ollama-", strip=True),),
        full_models=("gpt-oss:120b-cloud",),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )
    client = _FakeOllamaClient(config)

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_ollama_sidecar_config", load_config)
    monkeypatch.setattr("app.modules.proxy.api.OllamaSidecarClient", lambda _config: client)
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


@pytest.mark.asyncio
async def test_ollama_full_model_routes_to_sidecar_and_finalizes_reservation(
    async_client,
    ollama_enabled,
    fake_ollama,
):
    await async_client.put(
        "/api/settings",
        json={
            "ollamaSidecarEnabled": True,
            "ollamaSidecarApiKey": "ollama-key",
            "ollamaSidecarFullModels": ["gpt-oss:120b-cloud"],
        },
    )
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "ollama-key",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)],
    )

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": "gpt-oss:120b-cloud", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "hi"
    assert fake_ollama.chat_payloads[0]["model"] == "gpt-oss:120b-cloud"
    assert await _reservation_statuses() == ["finalized"]
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    sidecar_logs = [log for log in logs if log.source == "ollama_sidecar"]
    assert len(sidecar_logs) == 1
    assert sidecar_logs[0].model == "gpt-oss:120b-cloud"
    assert sidecar_logs[0].cost_usd is None


@pytest.mark.asyncio
async def test_ollama_prefix_routes_wire_model_and_logs_effective_model(
    async_client,
    ollama_enabled,
    fake_ollama,
):
    await async_client.put(
        "/api/settings",
        json={
            "ollamaSidecarEnabled": True,
            "ollamaSidecarApiKey": "ollama-key",
            "ollamaSidecarModelPrefixes": [{"prefix": "ollama-", "strip": True}],
        },
    )

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "ollama-gpt-oss:120b-cloud", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert fake_ollama.chat_payloads[0]["model"] == "gpt-oss:120b-cloud"
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    sidecar_logs = [log for log in logs if log.source == "ollama_sidecar"]
    assert sidecar_logs[0].model == "ollama-gpt-oss:120b-cloud"


@pytest.mark.asyncio
async def test_disabled_ollama_falls_through(async_client, ollama_enabled, fake_ollama, monkeypatch):
    await async_client.put(
        "/api/settings",
        json={
            "ollamaSidecarEnabled": False,
            "ollamaSidecarApiKey": "ollama-key",
            "ollamaSidecarModelPrefixes": [{"prefix": "ollama-", "strip": True}],
        },
    )
    disabled_config = replace(fake_ollama.config, enabled=False)

    async def load_disabled_config():
        return disabled_config

    monkeypatch.setattr("app.modules.proxy.api.load_ollama_sidecar_config", load_disabled_config)

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "ollama-gpt-oss:120b-cloud", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code in {502, 503}
    assert fake_ollama.chat_payloads == []


@pytest.mark.asyncio
async def test_api_key_allowed_models_use_effective_ollama_model(
    async_client,
    ollama_enabled,
    fake_ollama,
):
    await async_client.put(
        "/api/settings",
        json={
            "ollamaSidecarEnabled": True,
            "ollamaSidecarApiKey": "ollama-key",
            "ollamaSidecarModelPrefixes": [{"prefix": "ollama-", "strip": True}],
        },
    )
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("ollama-allowed", allowed_models=["ollama-gpt-oss:120b-cloud"])

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": "ollama-gpt-oss:120b-cloud", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert fake_ollama.chat_payloads[0]["model"] == "gpt-oss:120b-cloud"


@pytest.mark.asyncio
async def test_ollama_model_list_includes_configured_only(lifespan_free_client, ollama_enabled, fake_ollama):
    # Without the lifespan no cache-invalidation poller is registered, so the
    # settings write below is an in-process cache clear plus the temp-DB commit.
    from app.core.cache.invalidation import get_cache_invalidation_poller

    assert get_cache_invalidation_poller() is None

    settings_response = await lifespan_free_client.put(
        "/api/settings",
        json={
            "ollamaSidecarEnabled": True,
            "ollamaSidecarApiKey": "ollama-key",
            "ollamaSidecarFullModels": ["gpt-oss:120b-cloud"],
        },
    )
    assert settings_response.status_code == 200, settings_response.text

    response = await lifespan_free_client.get("/v1/models")

    assert response.status_code == 200
    data = response.json()["data"]
    ids = [item["id"] for item in data]
    assert "gpt-oss:120b-cloud" in ids
    assert "deepseek-v3.1:671b-cloud" not in ids
    sidecar_entry = next(item for item in data if item["id"] == "gpt-oss:120b-cloud")
    assert sidecar_entry["owned_by"] == "ollama"
    assert sidecar_entry["context_length"] == 200_000
