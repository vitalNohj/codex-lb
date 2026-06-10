from __future__ import annotations

import pytest

from app.core.clients.claude_sidecar import ClaudeSidecarConfig, SidecarModel
from app.core.openai.model_registry import ReasoningLevel, UpstreamModel, get_model_registry

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
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/models")
    assert response.status_code == 200
    models = response.json()["models"]
    assert {model["id"] for model in models} >= {"gpt-5.4", "claude-sonnet"}
    assert next(model for model in models if model["id"] == "claude-sonnet")["name"] == "Claude: claude-sonnet"
