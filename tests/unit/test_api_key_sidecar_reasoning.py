"""Key enforced reasoning wins on every sidecar payload builder.

Precedence is key enforced effort, then the sidecar default, then the client
value. A key with no enforced effort leaves the sidecar default in charge.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.clients.claude_sidecar import ClaudeSidecarConfig, SidecarPrefix
from app.core.clients.openai_compat_sidecar import OpenAICompatSidecarConfig
from app.core.clients.openrouter_sidecar import OpenRouterSidecarConfig
from app.core.clients.orcarouter_sidecar import OrcaRouterSidecarConfig
from app.core.exceptions import ProxyReasoningEffortNotAllowed
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.modules.api_keys.service import ApiKeyData, LimitRuleData
from app.modules.proxy.claude_sidecar_dispatch import build_sidecar_chat_payload
from app.modules.proxy.ollama_sidecar_dispatch import build_ollama_chat_payload
from app.modules.proxy.omniroute_sidecar_dispatch import build_omniroute_chat_payload
from app.modules.proxy.openai_compat_dispatch import build_openai_compat_chat_payload
from app.modules.proxy.opencode_go_sidecar_dispatch import build_opencode_go_chat_payload
from app.modules.proxy.openrouter_sidecar_dispatch import build_openrouter_chat_payload
from app.modules.proxy.orcarouter_sidecar_dispatch import build_orcarouter_chat_payload

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _key(
    enforced: str | None = None,
    *,
    allowed: list[str] | None = None,
    limits: list[LimitRuleData] | None = None,
    enforced_model: str | None = None,
) -> ApiKeyData:
    return ApiKeyData(
        id="ak_test",
        name="mikey",
        key_prefix="sk-test",
        allowed_models=None,
        enforced_model=enforced_model,
        enforced_reasoning_effort=enforced,
        enforced_service_tier=None,
        expires_at=None,
        is_active=True,
        created_at=_NOW,
        last_used_at=None,
        allowed_reasoning_efforts=allowed,
        limits=limits or [],
    )


def _effort_rule(*models: str, effort: str) -> LimitRuleData:
    return LimitRuleData(
        id=1,
        limit_type=None,
        limit_window=None,
        max_value=None,
        current_value=0,
        model_filter=models[0] if len(models) == 1 else None,
        model_filters=list(models),
        reset_at=None,
        reasoning_effort=effort,
    )


def _chat(**extra: object) -> ChatCompletionsRequest:
    body: dict[str, object] = {"model": "cc/claude-opus-5-5", "messages": [{"role": "user", "content": "hi"}]}
    body.update(extra)
    return ChatCompletionsRequest.model_validate(body)


def _claude_config(default: str | None) -> ClaudeSidecarConfig:
    return ClaudeSidecarConfig(
        enabled=True,
        base_url="http://127.0.0.1:8317",
        api_key="key",
        prefixes=(SidecarPrefix(prefix="cc/", strip=True),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        default_reasoning_effort=default,
    )


def _openrouter_config(default: str | None) -> OpenRouterSidecarConfig:
    return OpenRouterSidecarConfig(
        enabled=True,
        base_url="https://openrouter.ai/api/v1",
        api_key="key",
        prefixes=(SidecarPrefix(prefix="openrouter/", strip=True),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        default_reasoning_effort=default,
    )


def _orcarouter_config(default: str | None) -> OrcaRouterSidecarConfig:
    return OrcaRouterSidecarConfig(
        enabled=True,
        base_url="https://api.orcarouter.ai/v1",
        api_key="key",
        prefixes=(SidecarPrefix(prefix="orcarouter/", strip=True),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        default_reasoning_effort=default,
    )


def _compat_config(default: str | None) -> OpenAICompatSidecarConfig:
    return OpenAICompatSidecarConfig(
        endpoint_id="2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a",
        name="Vast",
        enabled=True,
        base_url="https://openai.vast.ai/demo/v1",
        api_key="key",
        prefixes=(SidecarPrefix(prefix="vast/", strip=True),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        default_reasoning_effort=default,
    )


def test_enforced_effort_wins_on_each_chat_sidecar_builder() -> None:
    key = _key("high")
    request = _chat(reasoning_effort="medium")

    built = [
        build_sidecar_chat_payload(request, "claude-opus-5-5", _claude_config("low"), api_key=key),
        build_openrouter_chat_payload(request, "deepseek/deepseek-chat", _openrouter_config("low"), api_key=key),
        build_orcarouter_chat_payload(request, "orcarouter/auto", _orcarouter_config("low"), api_key=key),
        build_openai_compat_chat_payload(request, "Qwen/Qwen2.5-7B", _compat_config("low"), api_key=key),
        build_omniroute_chat_payload(request, "omniroute/test-chat", "low", api_key=key),
        build_opencode_go_chat_payload(request, "glm-5.3", api_key=key),
    ]

    assert [(item.requested_reasoning_effort, item.body["reasoning_effort"]) for item in built] == [
        ("medium", "high")
    ] * len(built)
    assert [item.effective_reasoning_effort for item in built] == ["high"] * len(built)


def test_limit_rule_effort_wins_on_claude_sidecar_chat() -> None:
    key = _key(
        "low",
        limits=[_effort_rule("cc/claude-opus-5-5", effort="max")],
    )
    payload = build_sidecar_chat_payload(
        _chat(reasoning_effort="medium"),
        "claude-opus-5-5",
        _claude_config("high"),
        api_key=key,
    )

    assert payload.body["reasoning_effort"] == "max"
    assert (payload.requested_reasoning_effort, payload.effective_reasoning_effort) == ("medium", "max")


def test_sidecar_limit_rule_matches_the_enforced_model_not_the_client_model() -> None:
    key = _key(
        "low",
        enforced_model="cc/claude-opus-5-5",
        limits=[
            _effort_rule("cc/claude-haiku", effort="high"),
            _effort_rule("cc/claude-opus-5-5", effort="max"),
        ],
    )

    payload = build_sidecar_chat_payload(
        _chat(model="cc/claude-haiku", reasoning_effort="medium"),
        "claude-opus-5-5",
        _claude_config("high"),
        api_key=key,
    )

    assert payload.body["reasoning_effort"] == "max"
    assert (payload.requested_reasoning_effort, payload.effective_reasoning_effort) == ("medium", "max")


def test_sidecar_client_model_rule_does_not_apply_when_the_key_enforces_another_model() -> None:
    key = _key(
        "low",
        enforced_model="cc/claude-opus-5-5",
        limits=[_effort_rule("cc/claude-haiku", effort="max")],
    )

    payload = build_sidecar_chat_payload(
        _chat(model="cc/claude-haiku", reasoning_effort="medium"),
        "claude-opus-5-5",
        _claude_config("high"),
        api_key=key,
    )

    assert payload.body["reasoning_effort"] == "low"


def test_ollama_limit_rule_matches_the_enforced_model() -> None:
    key = _key(
        "low",
        enforced_model="gpt-oss:120b-cloud",
        limits=[
            _effort_rule("cc/claude-haiku", effort="high"),
            _effort_rule("gpt-oss:120b-cloud", effort="max"),
        ],
    )

    payload = build_ollama_chat_payload(
        _chat(model="cc/claude-haiku", reasoning_effort="medium"),
        "gpt-oss:120b-cloud",
        "low",
        api_key=key,
    )

    assert payload.body["model"] == "gpt-oss:120b-cloud"
    assert payload.body["think"] == "max"
    assert (payload.requested_reasoning_effort, payload.effective_reasoning_effort) == ("medium", "max")


def test_limit_rule_allowlist_still_rejects_the_client_effort() -> None:
    key = _key(
        allowed=["high"],
        limits=[_effort_rule("cc/claude-opus-5-5", effort="max")],
    )

    with pytest.raises(ProxyReasoningEffortNotAllowed):
        build_sidecar_chat_payload(
            _chat(reasoning_effort="low"),
            "claude-opus-5-5",
            _claude_config("high"),
            api_key=key,
        )


def test_enforced_effort_wins_on_ollama_think_field() -> None:
    payload = build_ollama_chat_payload(
        _chat(reasoning_effort="medium"),
        "gpt-oss:120b-cloud",
        "low",
        api_key=_key("high"),
    )

    assert payload.body["think"] == "high"
    assert payload.requested_reasoning_effort == "medium"
    assert payload.effective_reasoning_effort == "high"


def test_key_without_enforced_effort_keeps_the_sidecar_default() -> None:
    request = _chat(reasoning_effort="high")
    payload = build_sidecar_chat_payload(request, "claude-opus-5-5", _claude_config("low"), api_key=_key(None))

    assert payload.body["reasoning_effort"] == "low"
    assert (payload.requested_reasoning_effort, payload.effective_reasoning_effort) == ("high", "low")


def test_opencode_go_without_enforced_effort_keeps_the_client_value() -> None:
    payload = build_opencode_go_chat_payload(_chat(reasoning_effort="medium"), "glm-5.3", api_key=_key(None))

    assert payload.body["reasoning_effort"] == "medium"
    assert (payload.requested_reasoning_effort, payload.effective_reasoning_effort) == ("medium", "medium")


def test_captured_client_effort_is_what_the_log_records() -> None:
    request = _chat(reasoning_effort="high")
    request._codex_lb_client_reasoning_captured = True
    request._codex_lb_client_reasoning_effort = "medium"

    payload = build_sidecar_chat_payload(request, "claude-opus-5-5", _claude_config("low"), api_key=_key("high"))

    assert payload.body["reasoning_effort"] == "high"
    assert (payload.requested_reasoning_effort, payload.effective_reasoning_effort) == ("medium", "high")


def test_ultra_enforcement_is_sent_as_the_wire_max() -> None:
    payload = build_openrouter_chat_payload(
        _chat(),
        "deepseek/deepseek-chat",
        _openrouter_config("low"),
        api_key=_key("ultra"),
    )

    assert payload.body["reasoning_effort"] == "max"
    assert payload.requested_reasoning_effort is None


def test_allowlist_rejects_a_disallowed_client_effort_before_the_body_is_used() -> None:
    with pytest.raises(ProxyReasoningEffortNotAllowed):
        build_sidecar_chat_payload(
            _chat(reasoning_effort="low"),
            "claude-opus-5-5",
            _claude_config("high"),
            api_key=_key(allowed=["high"]),
        )


def test_ollama_allowlist_sees_reasoning_effort_and_thinking_true() -> None:
    key = _key(allowed=["high"])

    with pytest.raises(ProxyReasoningEffortNotAllowed):
        build_ollama_chat_payload(_chat(reasoning_effort="low"), "gpt-oss:120b-cloud", api_key=key)
    with pytest.raises(ProxyReasoningEffortNotAllowed):
        build_ollama_chat_payload(_chat(thinking=True), "gpt-oss:120b-cloud", api_key=key)
