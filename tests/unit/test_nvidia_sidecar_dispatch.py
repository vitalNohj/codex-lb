from __future__ import annotations

import pytest

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.nvidia_sidecar import NvidiaSidecarConfig
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.modules.proxy.claude_sidecar_dispatch import SidecarUsage, extract_billed_cost, extract_usage
from app.modules.proxy.nvidia_sidecar_dispatch import (
    _log_nvidia_request,
    _nvidia_request_cost,
    build_nvidia_chat_payload,
)


def _config(
    *,
    enabled: bool = True,
    prefixes: tuple[SidecarPrefix, ...] = (SidecarPrefix(prefix="deepseek/", strip=False),),
    default_reasoning_effort: str | None = None,
) -> NvidiaSidecarConfig:
    return NvidiaSidecarConfig(
        enabled=enabled,
        base_url="https://integrate.api.nvidia.com/v1",
        api_key="key",
        prefixes=prefixes,
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        default_reasoning_effort=default_reasoning_effort,
    )


def test_build_nvidia_chat_payload_preserves_extra_fields_and_effective_model() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "temperature": 0.2,
            "custom_flag": "kept",
        }
    )

    payload = build_nvidia_chat_payload(request, "z-ai/glm-5.3", _config())

    assert payload.body["model"] == "z-ai/glm-5.3"
    assert payload.body["messages"] == [{"role": "user", "content": "hi"}]
    assert payload.body["custom_flag"] == "kept"


def test_build_nvidia_chat_payload_injects_override_effort_when_absent() -> None:
    request = ChatCompletionsRequest.model_validate(
        {"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]}
    )

    payload = build_nvidia_chat_payload(request, "z-ai/glm-5.3", _config(default_reasoning_effort="high"))

    assert payload.body["reasoning_effort"] == "high"


def test_build_nvidia_chat_payload_override_replaces_client_effort() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "reasoning_effort": "low",
        }
    )

    payload = build_nvidia_chat_payload(request, "z-ai/glm-5.3", _config(default_reasoning_effort="high"))

    assert payload.body["reasoning_effort"] == "high"


def test_build_nvidia_chat_payload_override_replaces_nested_reasoning() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "reasoning": {"effort": "minimal"},
        }
    )

    payload = build_nvidia_chat_payload(request, "z-ai/glm-5.3", _config(default_reasoning_effort="high"))

    assert payload.body["reasoning_effort"] == "high"
    assert "reasoning" not in payload.body


def _install_catalog_price(monkeypatch: pytest.MonkeyPatch, cost: object) -> None:
    from app.core.usage.external_pricing.service import CalculatedCost
    from app.db.models import ExternalPriceStatus
    from app.modules.proxy import external_pricing_logging

    async def _calculated_cost(**_kwargs: object) -> tuple[object, object]:
        if cost is None:
            return None, ExternalPriceStatus.UNRESOLVED
        assert isinstance(cost, CalculatedCost)
        return cost, ExternalPriceStatus.RESOLVED

    monkeypatch.setattr(external_pricing_logging, "calculated_cost_for_request", _calculated_cost)


@pytest.mark.asyncio
async def test_log_nvidia_request_uses_catalog_price_not_echoed_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.usage.external_pricing.service import CalculatedCost

    _install_catalog_price(monkeypatch, CalculatedCost(0.25, "z-ai/glm-5.3", "nvidia"))
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

    monkeypatch.setattr("app.modules.proxy.nvidia_sidecar_dispatch.get_background_session", _SessionContext)
    monkeypatch.setattr("app.modules.proxy.nvidia_sidecar_dispatch.RequestLogsRepository", _Repository)
    monkeypatch.setattr("app.modules.proxy.nvidia_sidecar_dispatch.get_request_id", lambda: "req-nvidia-cost")

    await _log_nvidia_request(
        api_key=None,
        model="z-ai/glm-5.3",
        started_at=0,
        status="success",
        usage=SidecarUsage(input_tokens=10, output_tokens=5, cost_usd=0.00123),
    )

    assert len(calls) == 1
    assert calls[0]["request_id"] == "req-nvidia-cost"
    assert calls[0]["source"] == "nvidia_sidecar"
    assert calls[0]["cost_usd"] == pytest.approx(0.25)
    assert calls[0]["cost_source"] == "catalog_calculated"


@pytest.mark.asyncio
async def test_nvidia_echoed_cost_is_not_upstream_billed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_catalog_price(monkeypatch, None)
    payload = {"usage": {"prompt_tokens": 10, "cost": 0.01}}
    usage = extract_usage(payload)
    cost = await _nvidia_request_cost(
        "z-ai/glm-5.3",
        usage,
        billed_cost_usd=extract_billed_cost(payload),
    )

    assert cost.cost_usd is None
    assert cost.cost_source is None


@pytest.mark.asyncio
async def test_log_nvidia_request_records_reference_cost_without_billed_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.usage.pricing import ModelPrice
    from app.core.usage.runtime_pricing import get_runtime_pricing_registry

    _install_catalog_price(monkeypatch, None)
    registry = get_runtime_pricing_registry()
    registry.clear()
    registry.update_models(
        [("z-ai/glm-5.3", ModelPrice(input_per_1m=0.8, output_per_1m=4.0))],
        provider="nvidia",
    )

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

    monkeypatch.setattr("app.modules.proxy.nvidia_sidecar_dispatch.get_background_session", _SessionContext)
    monkeypatch.setattr("app.modules.proxy.nvidia_sidecar_dispatch.RequestLogsRepository", _Repository)
    monkeypatch.setattr("app.modules.proxy.nvidia_sidecar_dispatch.get_request_id", lambda: "req-ref")

    await _log_nvidia_request(
        api_key=None,
        model="z-ai/glm-5.3",
        started_at=0,
        status="success",
        usage=SidecarUsage(input_tokens=10_000, output_tokens=2_000, cost_usd=0.0),
    )

    registry.clear()
    assert len(calls) == 1
    assert calls[0]["cost_usd"] is None
    assert calls[0]["cost_source"] is None
    assert calls[0]["reference_cost_usd"] == pytest.approx(0.016)


def test_build_nvidia_chat_payload_captures_requested_and_effective_with_override() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "reasoning_effort": "medium",
        }
    )

    payload = build_nvidia_chat_payload(request, "z-ai/glm-5.3", _config(default_reasoning_effort="high"))

    assert payload.requested_reasoning_effort == "medium"
    assert payload.effective_reasoning_effort == "high"


def test_build_nvidia_chat_payload_requested_equals_effective_without_override() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "reasoning_effort": "high",
        }
    )

    payload = build_nvidia_chat_payload(request, "z-ai/glm-5.3", _config())

    assert payload.requested_reasoning_effort == "high"
    assert payload.effective_reasoning_effort == "high"


def test_build_nvidia_chat_payload_requested_none_effective_override() -> None:
    request = ChatCompletionsRequest.model_validate(
        {"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]}
    )

    payload = build_nvidia_chat_payload(request, "z-ai/glm-5.3", _config(default_reasoning_effort="low"))

    assert payload.requested_reasoning_effort is None
    assert payload.effective_reasoning_effort == "low"
