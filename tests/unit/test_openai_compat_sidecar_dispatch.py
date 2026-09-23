from __future__ import annotations

import json

import pytest

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.openai_compat_sidecar import (
    OpenAICompatSidecarConfig,
    get_openai_compat_sidecar_client,
    reset_openai_compat_sidecar_client_cache,
)
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.db.models import DashboardSettings
from app.modules.proxy.claude_sidecar_dispatch import SidecarUsage, extract_billed_cost, extract_usage
from app.modules.proxy.openai_compat_dispatch import (
    _log_openai_compat_request,
    _openai_compat_request_cost,
    build_openai_compat_chat_payload,
    openai_compat_configs_from_settings,
)

ENDPOINT_ID = "2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a"
PROVIDER_ID = f"openai_compat:{ENDPOINT_ID}"


def _config(
    *,
    enabled: bool = True,
    prefixes: tuple[SidecarPrefix, ...] = (SidecarPrefix(prefix="vast/", strip=True),),
    default_reasoning_effort: str | None = None,
    api_key: str | None = None,
) -> OpenAICompatSidecarConfig:
    return OpenAICompatSidecarConfig(
        endpoint_id=ENDPOINT_ID,
        name="Vast",
        enabled=enabled,
        base_url="https://openai.vast.ai/demo/v1",
        api_key=api_key,
        prefixes=prefixes,
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        default_reasoning_effort=default_reasoning_effort,
    )


def test_build_openai_compat_chat_payload_preserves_extra_fields_and_effective_model() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "temperature": 0.2,
            "custom_flag": "kept",
        }
    )

    payload = build_openai_compat_chat_payload(request, "Qwen/Qwen2.5-7B", _config())

    assert payload.body["model"] == "Qwen/Qwen2.5-7B"
    assert payload.body["messages"] == [{"role": "user", "content": "hi"}]
    assert payload.body["custom_flag"] == "kept"


def test_build_openai_compat_chat_payload_injects_override_effort_when_absent() -> None:
    request = ChatCompletionsRequest.model_validate(
        {"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]}
    )

    payload = build_openai_compat_chat_payload(request, "Qwen/Qwen2.5-7B", _config(default_reasoning_effort="high"))

    assert payload.body["reasoning_effort"] == "high"


def test_build_openai_compat_chat_payload_override_replaces_client_effort() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "reasoning_effort": "low",
        }
    )

    payload = build_openai_compat_chat_payload(request, "Qwen/Qwen2.5-7B", _config(default_reasoning_effort="high"))

    assert payload.body["reasoning_effort"] == "high"


def test_build_openai_compat_chat_payload_override_replaces_nested_reasoning() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "reasoning": {"effort": "minimal"},
        }
    )

    payload = build_openai_compat_chat_payload(request, "Qwen/Qwen2.5-7B", _config(default_reasoning_effort="high"))

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
async def test_log_openai_compat_request_uses_catalog_price_not_echoed_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.usage.external_pricing.service import CalculatedCost

    _install_catalog_price(monkeypatch, CalculatedCost(0.25, "Qwen/Qwen2.5-7B", PROVIDER_ID))
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

    class _Client:
        config = _config()

    monkeypatch.setattr("app.modules.proxy.openai_compat_dispatch.get_background_session", _SessionContext)
    monkeypatch.setattr("app.modules.proxy.openai_compat_dispatch.RequestLogsRepository", _Repository)
    monkeypatch.setattr("app.modules.proxy.openai_compat_dispatch.get_request_id", lambda: "req-compat-cost")

    await _log_openai_compat_request(
        api_key=None,
        model="Qwen/Qwen2.5-7B",
        started_at=0,
        status="success",
        usage=SidecarUsage(input_tokens=10, output_tokens=5, cost_usd=0.00123),
        client=_Client(),
    )

    assert len(calls) == 1
    assert calls[0]["request_id"] == "req-compat-cost"
    assert calls[0]["source"] == PROVIDER_ID
    assert calls[0]["transport"] == "http"
    assert calls[0]["cost_usd"] == pytest.approx(0.25)
    assert calls[0]["cost_source"] == "catalog_calculated"


@pytest.mark.asyncio
async def test_openai_compat_echoed_cost_is_not_upstream_billed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_catalog_price(monkeypatch, None)
    payload = {"usage": {"prompt_tokens": 10, "cost": 0.01}}
    usage = extract_usage(payload)
    cost = await _openai_compat_request_cost(
        "Qwen/Qwen2.5-7B",
        usage,
        billed_cost_usd=extract_billed_cost(payload),
        provider=PROVIDER_ID,
    )

    assert cost.cost_usd is None
    assert cost.cost_source is None


@pytest.mark.asyncio
async def test_log_openai_compat_request_records_reference_cost_without_billed_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.usage.pricing import ModelPrice
    from app.core.usage.runtime_pricing import get_runtime_pricing_registry

    _install_catalog_price(monkeypatch, None)
    registry = get_runtime_pricing_registry()
    registry.clear()
    registry.update_models(
        [("Qwen/Qwen2.5-7B", ModelPrice(input_per_1m=0.8, output_per_1m=4.0))],
        provider=PROVIDER_ID,
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

    class _Client:
        config = _config()

    monkeypatch.setattr("app.modules.proxy.openai_compat_dispatch.get_background_session", _SessionContext)
    monkeypatch.setattr("app.modules.proxy.openai_compat_dispatch.RequestLogsRepository", _Repository)
    monkeypatch.setattr("app.modules.proxy.openai_compat_dispatch.get_request_id", lambda: "req-ref")

    await _log_openai_compat_request(
        api_key=None,
        model="Qwen/Qwen2.5-7B",
        started_at=0,
        status="success",
        usage=SidecarUsage(input_tokens=10_000, output_tokens=2_000, cost_usd=0.0),
        client=_Client(),
    )

    registry.clear()
    assert len(calls) == 1
    assert calls[0]["cost_usd"] is None
    assert calls[0]["cost_source"] is None
    assert calls[0]["reference_cost_usd"] == pytest.approx(0.016)


def test_build_openai_compat_chat_payload_captures_requested_and_effective_with_override() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "reasoning_effort": "medium",
        }
    )

    payload = build_openai_compat_chat_payload(request, "Qwen/Qwen2.5-7B", _config(default_reasoning_effort="high"))

    assert payload.requested_reasoning_effort == "medium"
    assert payload.effective_reasoning_effort == "high"


def test_build_openai_compat_chat_payload_requested_equals_effective_without_override() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "reasoning_effort": "high",
        }
    )

    payload = build_openai_compat_chat_payload(request, "Qwen/Qwen2.5-7B", _config())

    assert payload.requested_reasoning_effort == "high"
    assert payload.effective_reasoning_effort == "high"


def test_build_openai_compat_chat_payload_requested_none_effective_override() -> None:
    request = ChatCompletionsRequest.model_validate(
        {"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]}
    )

    payload = build_openai_compat_chat_payload(request, "Qwen/Qwen2.5-7B", _config(default_reasoning_effort="low"))

    assert payload.requested_reasoning_effort is None
    assert payload.effective_reasoning_effort == "low"


def test_loading_configs_reconciles_the_client_cache_with_the_current_endpoints(monkeypatch) -> None:
    """The reconciliation must be wired into the settings read, not merely exist.

    ``openai_compat_configs_from_settings`` is every caller's route from the
    stored blob to a routable config, so it is where we learn which endpoints
    still exist. Without this call a deleted endpoint's cached client - and its
    decrypted API key - survived for the whole process lifetime
    (https://github.com/vitalNohj/codex-lb/pull/59).
    """

    reset_openai_compat_sidecar_client_cache()
    removed_id = "3d0c9a4b-2f5e-4c8b-8d22-8b1f5e3c2d1b"
    removed = get_openai_compat_sidecar_client(_config())
    kept_config = OpenAICompatSidecarConfig(
        endpoint_id=removed_id,
        name="vLLM",
        enabled=True,
        base_url="https://vllm.internal/v1",
        api_key=None,
        prefixes=(SidecarPrefix(prefix="vllm/", strip=True),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=(),
    )
    kept = get_openai_compat_sidecar_client(kept_config)

    # A settings blob that lists only the endpoint that still exists.
    settings = DashboardSettings(
        id=1,
        openai_compat_endpoints_json=json.dumps(
            [
                {
                    "id": removed_id,
                    "name": "vLLM",
                    "enabled": True,
                    "base_url": "https://vllm.internal/v1",
                }
            ]
        ),
    )

    openai_compat_configs_from_settings(settings)

    assert get_openai_compat_sidecar_client(kept_config) is kept
    assert get_openai_compat_sidecar_client(_config()) is not removed
    reset_openai_compat_sidecar_client_cache()
