from __future__ import annotations

import pytest

from app.core.clients.claude_sidecar import ClaudeSidecarConfig, SidecarModel
from app.core.openai.model_registry import ReasoningLevel, UpstreamModel, get_model_registry
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
