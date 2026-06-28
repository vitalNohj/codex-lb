from __future__ import annotations

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.omniroute_sidecar import OmniRouteSidecarConfig
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.modules.proxy.omniroute_sidecar_dispatch import build_omniroute_chat_payload


def _config(
    *,
    enabled: bool = True,
    full_models: tuple[str, ...] = ("omniroute/test-chat",),
) -> OmniRouteSidecarConfig:
    return OmniRouteSidecarConfig(
        enabled=enabled,
        base_url="http://127.0.0.1:20128/v1",
        api_key="key",
        full_models=full_models,
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        prefixes=(SidecarPrefix(prefix="omni-", strip=True),),
    )


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


def test_build_omniroute_chat_payload_injects_override_effort_when_absent() -> None:
    request = ChatCompletionsRequest.model_validate(
        {"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}]}
    )

    payload = build_omniroute_chat_payload(request, "omniroute/test-chat", "high")

    assert payload.body["reasoning_effort"] == "high"


def test_build_omniroute_chat_payload_override_replaces_client_effort() -> None:
    request = ChatCompletionsRequest.model_validate(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
            "reasoning_effort": "low",
        }
    )

    payload = build_omniroute_chat_payload(request, "omniroute/test-chat", "high")

    assert payload.body["reasoning_effort"] == "high"
