from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clients.claude_sidecar import ClaudeSidecarConfig, SidecarModel
from app.core.clients.openai_compat_sidecar import OpenAICompatSidecarConfig
from app.core.clients.opencode_go_sidecar import OpenCodeGoSidecarConfig
from app.core.clients.openrouter_sidecar import OpenRouterSidecarConfig
from app.core.clients.orcarouter_sidecar import OrcaRouterSidecarConfig
from app.core.openai.model_registry import (
    MODEL_SOURCE_KIND_OPENAI_COMPATIBLE,
    ReasoningLevel,
    UpstreamModel,
    get_model_registry,
)
from app.db.models import ModelSource, ModelSourceModel
from app.modules.api_keys.model_filters import encode_model_filters, limit_matches_request_model

pytestmark = pytest.mark.integration


class _FakeSidecarClient:
    def __init__(self, _config: ClaudeSidecarConfig) -> None:
        pass

    async def list_models_cached(self) -> list[SidecarModel]:
        return [SidecarModel(id="claude-sonnet", created=123, owned_by="anthropic")]


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


@pytest.mark.asyncio
async def test_dashboard_models_append_sidecar_models_when_enabled(async_client, monkeypatch):
    registry = get_model_registry()
    await registry.update({"plus": [_make_upstream_model("gpt-5.4")]})
    monkeypatch.setattr("app.modules.dashboard.api.ClaudeSidecarClient", _FakeSidecarClient)
    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarApiKey": "sidecar-key",
            "claudeSidecarModelPrefixes": [{"prefix": "claude", "strip": False}],
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/models")
    assert response.status_code == 200
    models = response.json()["models"]
    assert {model["id"] for model in models} >= {"gpt-5.4", "claude-sonnet"}
    assert next(model for model in models if model["id"] == "claude-sonnet")["name"] == "CLIProxyAPI: claude-sonnet"


class _AliasListingClient:
    def __init__(self, _config: ClaudeSidecarConfig) -> None:
        pass

    async def list_models_cached(self) -> list[SidecarModel]:
        return [
            SidecarModel(id="lb2a7d4938e6/claude-sonnet-5", created=1, owned_by="anthropic"),
            SidecarModel(id="claude-opus-4-20250514", created=2, owned_by="anthropic"),
            SidecarModel(id="grok-4.6", created=3, owned_by="xai"),
            SidecarModel(id="lb2a7d4938e6/claude-haiku-4-5-20251001", created=4, owned_by="anthropic"),
            SidecarModel(id="claude-sonnet-4-6", created=5, owned_by="anthropic"),
            SidecarModel(id="claude-opus-5-5", created=6, owned_by="anthropic"),
        ]


@pytest.mark.asyncio
async def test_dashboard_models_list_cliproxy_client_ids(async_client, monkeypatch):
    """A picked CLIProxyAPI id is the client model a limit compares."""

    registry = get_model_registry()
    await registry.update({"plus": [_make_upstream_model("gpt-5.4")]})
    monkeypatch.setattr("app.modules.dashboard.api.ClaudeSidecarClient", _AliasListingClient)
    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarApiKey": "sidecar-key",
            "claudeSidecarModelPrefixes": [{"prefix": "cc/", "strip": True}],
            "claudeSidecarFullModels": ["claude-opus-5-5"],
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/models")
    assert response.status_code == 200
    models = response.json()["models"]
    by_id = {model["id"]: model for model in models}
    assert "cc/claude-opus-5-5" in by_id
    assert "cc/claude-sonnet-5" in by_id
    assert "cc/grok-4.6" in by_id
    assert "cc/claude-haiku-4-5-20251001" in by_id
    assert "cc/claude-sonnet-4-6" in by_id
    assert "claude-opus-5-5" in by_id
    assert "lb2a7d4938e6/claude-sonnet-5" not in by_id
    assert "lb2a7d4938e6/claude-haiku-4-5-20251001" not in by_id
    assert by_id["cc/claude-opus-5-5"]["name"] == "CLIProxyAPI: cc/claude-opus-5-5"
    assert by_id["cc/grok-4.6"]["name"] == "CLIProxyAPI: cc/grok-4.6"
    assert all(not model["name"].startswith("Claude:") for model in models if model["id"].startswith("cc/"))

    picked = by_id["cc/claude-opus-5-5"]["id"]
    stored = encode_model_filters([picked])
    assert limit_matches_request_model(stored, "cc/claude-opus-5-5") is True


class _SubscriptionCatalogClient:
    """Auth files carry the provider; each file's catalog carries its models."""

    def __init__(self, _config: ClaudeSidecarConfig) -> None:
        self.calls: list[str] = []

    async def list_models_cached(self) -> list[SidecarModel]:
        raise AssertionError("the subscription scope must not use the shared model list")

    async def list_auth_files(self) -> list[dict[str, str]]:
        return [
            {"name": "claude-a.json", "provider": "claude"},
            {"name": "grok-a.json", "provider": "xai"},
            {"name": "codex-a.json", "provider": "codex"},
            {"name": "gemini-a.json", "provider": "gemini"},
        ]

    async def list_auth_file_models(self, name: str) -> list[str]:
        self.calls.append(name)
        catalogs = {
            "claude-a.json": ["lb2a7d4938e6/claude-opus-4-20250514", "claude-sonnet-4-6"],
            "grok-a.json": ["grok-4"],
            "codex-a.json": ["gpt-5.4", "gpt-5.3-codex"],
            "gemini-a.json": ["gemini-2.5-pro"],
        }
        return catalogs[name]


class _NamedCatalogClient:
    """One configured integration's catalog, labelled so the test can tell them apart."""

    model_id = "integration-model"

    def __init__(
        self,
        _config: (
            OpenRouterSidecarConfig | OpenAICompatSidecarConfig | OrcaRouterSidecarConfig | OpenCodeGoSidecarConfig
        ),
    ) -> None:
        pass

    async def list_models_cached(self) -> list[SidecarModel]:
        return [SidecarModel(id=self.model_id, created=1, owned_by="test")]


class _OpenRouterCatalog(_NamedCatalogClient):
    model_id = "openrouter/deepseek-chat"


class _OpenAICompatCatalog(_NamedCatalogClient):
    model_id = "Qwen/Qwen2.5-7B"


class _OrcaRouterCatalog(_NamedCatalogClient):
    model_id = "orcarouter/glm-5"


class _OpenCodeGoCatalog(_NamedCatalogClient):
    model_id = "glm-5.3"


class _ModelSourceRepository:
    def __init__(self, _session: AsyncSession) -> None:
        pass

    async def list_enabled_sources(self) -> list[ModelSource]:
        return [
            ModelSource(
                id="src-local",
                name="Local",
                kind=MODEL_SOURCE_KIND_OPENAI_COMPATIBLE,
                base_url="http://127.0.0.1:8000/v1",
                is_enabled=True,
                models=[ModelSourceModel(model="local-llama", display_name="Local Llama", is_enabled=True)],
            )
        ]


@pytest.mark.asyncio
async def test_subscription_models_keep_codex_and_claude_xai_logins(async_client, monkeypatch):
    """Limit-rule scope filters CLIProxyAPI only.

    Codex registry models and every other configured integration stay. A
    Codex or other CLIProxyAPI login does not.
    """

    registry = get_model_registry()
    await registry.update({"plus": [_make_upstream_model("gpt-5.4")]})
    monkeypatch.setattr("app.modules.dashboard.api.ClaudeSidecarClient", _SubscriptionCatalogClient)
    monkeypatch.setattr("app.modules.dashboard.api.OpenRouterSidecarClient", _OpenRouterCatalog)
    monkeypatch.setattr(
        "app.modules.dashboard.api.get_openai_compat_sidecar_client",
        lambda _config: _OpenAICompatCatalog(None),
    )
    monkeypatch.setattr(
        "app.modules.dashboard.api.get_orcarouter_sidecar_client",
        lambda _config: _OrcaRouterCatalog(None),
    )
    monkeypatch.setattr(
        "app.modules.dashboard.api.get_opencode_go_sidecar_client",
        lambda _config: _OpenCodeGoCatalog(None),
    )
    monkeypatch.setattr("app.modules.dashboard.api.ModelSourcesRepository", _ModelSourceRepository)
    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarApiKey": "sidecar-key",
            "claudeSidecarModelPrefixes": [{"prefix": "cc/", "strip": True}],
            "claudeSidecarFullModels": ["claude-sonnet-4-6", "gpt-5.3-codex"],
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
            "openaiCompatEndpoints": [
                {
                    "id": "2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a",
                    "name": "Vast",
                    "enabled": True,
                    "baseUrl": "https://openai.vast.ai/demo/v1",
                    "modelPrefixes": [],
                    "fullModels": ["Qwen/Qwen2.5-7B"],
                }
            ],
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "orcarouter-key",
            "opencodeGoSidecarEnabled": True,
            "opencodeGoSidecarApiKey": "opencode-go-key",
        },
    )
    assert response.status_code == 200, response.text

    scoped = await async_client.get("/api/models", params={"scope": "subscriptions"})
    unscoped = await async_client.get("/api/models")
    assert scoped.status_code == 200
    assert unscoped.status_code == 200
    models = scoped.json()["models"]
    by_id = {model["id"]: model for model in models}
    assert "gpt-5.4" in by_id
    assert by_id["gpt-5.4"]["name"] == "gpt-5.4"
    assert "cc/claude-opus-4-20250514" in by_id
    assert "cc/claude-sonnet-4-6" in by_id
    assert "claude-sonnet-4-6" in by_id
    assert "cc/grok-4" in by_id
    assert by_id["cc/grok-4"]["name"] == "CLIProxyAPI: cc/grok-4"
    assert by_id["openrouter/deepseek-chat"]["name"] == "OpenRouter: openrouter/deepseek-chat"
    assert by_id["Qwen/Qwen2.5-7B"]["name"] == "Vast: Qwen/Qwen2.5-7B"
    assert by_id["orcarouter/glm-5"]["name"] == "OrcaRouter: orcarouter/glm-5"
    assert by_id["glm-5.3"]["name"] == "OpenCode Go: glm-5.3"
    assert by_id["local-llama"]["name"] == "Local Llama"
    assert by_id["local-llama"]["sourceOnly"] is True
    assert "gpt-5.3-codex" not in by_id
    assert "cc/gpt-5.3-codex" not in by_id
    assert "cc/gpt-5.4" not in by_id
    assert "gemini-2.5-pro" not in by_id
    assert "cc/gemini-2.5-pro" not in by_id
    assert "lb2a7d4938e6/claude-opus-4-20250514" not in by_id
    # The scope changes nothing outside CLIProxyAPI, so the two lists agree
    # once the shared CLIProxyAPI listing (which this scope does not call) is set aside.
    unscoped_other = [model for model in unscoped.json()["models"] if not str(model["name"]).startswith("CLIProxyAPI:")]
    scoped_other = [model for model in models if not str(model["name"]).startswith("CLIProxyAPI:")]
    assert scoped_other == unscoped_other
