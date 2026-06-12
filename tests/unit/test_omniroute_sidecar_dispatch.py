from __future__ import annotations

from app.core.clients.omniroute_sidecar import OmniRouteSidecarConfig
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.modules.proxy.omniroute_sidecar_dispatch import build_omniroute_chat_payload, is_omniroute_sidecar_model


def _config(
    *,
    enabled: bool = True,
    selected_models: tuple[str, ...] = ("omniroute/test-chat",),
) -> OmniRouteSidecarConfig:
    return OmniRouteSidecarConfig(
        enabled=enabled,
        base_url="http://127.0.0.1:20128/v1",
        api_key="key",
        selected_models=selected_models,
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )


def test_is_omniroute_sidecar_model_respects_enabled_and_exact_selection() -> None:
    enabled = _config()
    disabled = _config(enabled=False)

    assert is_omniroute_sidecar_model("omniroute/test-chat", enabled) is True
    assert is_omniroute_sidecar_model("OmniRoute/Test-Chat", enabled) is True
    assert is_omniroute_sidecar_model("omniroute/test-chat-plus", enabled) is False
    assert is_omniroute_sidecar_model("omniroute/test-chat", disabled) is False


def test_build_omniroute_chat_payload_preserves_extra_fields_and_effective_model() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "temperature": 0.2,
            "custom_flag": "kept",
        }
    )

    payload = build_omniroute_chat_payload(request, "omniroute/test-chat")

    assert payload.body["model"] == "omniroute/test-chat"
    assert payload.body["messages"] == [{"role": "user", "content": "hi"}]
    assert payload.body["custom_flag"] == "kept"
