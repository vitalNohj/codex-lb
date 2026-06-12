from __future__ import annotations

from app.core.clients.openrouter_sidecar import OpenRouterSidecarConfig
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.modules.proxy.openrouter_sidecar_dispatch import (
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
