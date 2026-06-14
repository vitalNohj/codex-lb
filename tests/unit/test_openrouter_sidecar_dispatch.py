from __future__ import annotations

import pytest

from app.core.clients.openrouter_sidecar import OpenRouterSidecarConfig
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.modules.proxy.claude_sidecar_dispatch import SidecarUsage
from app.modules.proxy.openrouter_sidecar_dispatch import (
    _log_openrouter_request,
    build_openrouter_chat_payload,
    is_openrouter_sidecar_model,
    openrouter_sidecar_wire_model,
)


def _config(*, enabled: bool = True, prefixes: tuple[str, ...] = ("deepseek/",)) -> OpenRouterSidecarConfig:
    return OpenRouterSidecarConfig(
        enabled=enabled,
        base_url="https://openrouter.ai/api/v1",
        api_key="key",
        model_prefixes=prefixes,
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )


def test_is_openrouter_sidecar_model_respects_enabled_prefix_and_case() -> None:
    enabled = _config()
    disabled = _config(enabled=False)

    assert is_openrouter_sidecar_model("deepseek/deepseek-chat", enabled) is True
    assert is_openrouter_sidecar_model("DeepSeek/deepseek-chat", enabled) is True
    assert is_openrouter_sidecar_model("gpt-5.4", enabled) is False
    assert is_openrouter_sidecar_model("deepseek/deepseek-chat", disabled) is False


def test_is_openrouter_sidecar_model_treats_dash_and_underscore_alias_prefixes_as_equivalent() -> None:
    enabled = _config(prefixes=("or-",))

    assert is_openrouter_sidecar_model("or-deepseek/deepseek-chat", enabled) is True
    assert is_openrouter_sidecar_model("or_deepseek/deepseek-chat", enabled) is True


def test_openrouter_sidecar_wire_model_strips_custom_alias_prefix_only() -> None:
    alias_config = _config(prefixes=("or-",))
    direct_config = _config(prefixes=("deepseek/",))

    assert openrouter_sidecar_wire_model("or-deepseek/deepseek-chat", alias_config) == "deepseek/deepseek-chat"
    assert openrouter_sidecar_wire_model("or_deepseek/deepseek-chat", alias_config) == "deepseek/deepseek-chat"
    assert openrouter_sidecar_wire_model("deepseek/deepseek-chat", direct_config) == "deepseek/deepseek-chat"


def test_build_openrouter_chat_payload_preserves_extra_fields_and_effective_model() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "temperature": 0.2,
            "custom_flag": "kept",
        }
    )

    payload = build_openrouter_chat_payload(request, "deepseek/deepseek-chat", _config())

    assert payload.body["model"] == "deepseek/deepseek-chat"
    assert payload.body["messages"] == [{"role": "user", "content": "hi"}]
    assert payload.body["custom_flag"] == "kept"


@pytest.mark.asyncio
async def test_log_openrouter_request_passes_authoritative_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class _SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

    class _Repository:
        def __init__(self, session: object) -> None:
            self.session = session

        async def add_log(self, **kwargs: object) -> None:
            calls.append(kwargs)

    monkeypatch.setattr("app.modules.proxy.openrouter_sidecar_dispatch.get_background_session", _SessionContext)
    monkeypatch.setattr("app.modules.proxy.openrouter_sidecar_dispatch.RequestLogsRepository", _Repository)
    monkeypatch.setattr("app.modules.proxy.openrouter_sidecar_dispatch.get_request_id", lambda: "req-openrouter-cost")

    await _log_openrouter_request(
        api_key=None,
        model="deepseek/deepseek-chat",
        started_at=0,
        status="success",
        usage=SidecarUsage(input_tokens=10, output_tokens=5, cost_usd=0.00123),
    )

    assert len(calls) == 1
    assert calls[0]["request_id"] == "req-openrouter-cost"
    assert calls[0]["source"] == "openrouter_sidecar"
    assert calls[0]["cost_usd"] == 0.00123


@pytest.mark.asyncio
async def test_log_openrouter_free_request_records_reference_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.usage.pricing import ModelPrice
    from app.core.usage.runtime_pricing import get_runtime_pricing_registry

    registry = get_runtime_pricing_registry()
    registry.clear()
    registry.update_models([("vendor/model-x", ModelPrice(input_per_1m=0.8, output_per_1m=4.0))])

    calls: list[dict[str, object]] = []

    class _SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

    class _Repository:
        def __init__(self, session: object) -> None:
            self.session = session

        async def add_log(self, **kwargs: object) -> None:
            calls.append(kwargs)

    monkeypatch.setattr("app.modules.proxy.openrouter_sidecar_dispatch.get_background_session", _SessionContext)
    monkeypatch.setattr("app.modules.proxy.openrouter_sidecar_dispatch.RequestLogsRepository", _Repository)
    monkeypatch.setattr("app.modules.proxy.openrouter_sidecar_dispatch.get_request_id", lambda: "req-free")

    await _log_openrouter_request(
        api_key=None,
        model="vendor/model-x:free",
        started_at=0,
        status="success",
        usage=SidecarUsage(input_tokens=10_000, output_tokens=2_000, cost_usd=0.0),
    )

    registry.clear()
    assert len(calls) == 1
    # Free model: actual spend is 0 but reference (paid-equivalent) cost is recorded.
    assert calls[0]["cost_usd"] == 0.0
    assert calls[0]["reference_cost_usd"] == pytest.approx(0.016)
