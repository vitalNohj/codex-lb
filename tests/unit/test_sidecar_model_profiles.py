from __future__ import annotations

from app.core.clients.claude_sidecar import ClaudeSidecarConfig, SidecarPrefix
from app.core.types import JsonValue
from app.modules.proxy.sidecar_model_profiles import (
    apply_sidecar_model_profile,
    canonical_sidecar_model,
    is_known_claude_sidecar_model,
    sidecar_prefixed_model_ids,
)


def _config(*, prefixes: tuple[str, ...] = ("cp-",)) -> ClaudeSidecarConfig:
    return ClaudeSidecarConfig(
        enabled=True,
        base_url="http://127.0.0.1:8317",
        api_key="key",
        prefixes=tuple(SidecarPrefix(prefix=prefix, strip=prefix.endswith(("-", "_"))) for prefix in prefixes),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )


def test_canonical_sidecar_model_strips_only_a_routing_prefix() -> None:
    assert canonical_sidecar_model("cp-claude-opus-4-7") == "claude-opus-4-7"
    assert canonical_sidecar_model("cp-claude-opus-4-8") == "claude-opus-4-8"
    assert canonical_sidecar_model("cp-claude-fable-5") == "claude-fable-5"
    assert canonical_sidecar_model("cc/claude-fable-5-1") == "claude-fable-5-1"
    assert canonical_sidecar_model("claude-fable-5.1") == "claude-fable-5.1"
    assert canonical_sidecar_model("cc/claude-opus-5-5") == "claude-opus-5-5"
    assert canonical_sidecar_model("claude-opus-5.5") == "claude-opus-5.5"
    assert canonical_sidecar_model("cc/claude-sonnet-5-5") == "claude-sonnet-5-5"
    assert canonical_sidecar_model("claude-sonnet-5.5") == "claude-sonnet-5.5"
    assert canonical_sidecar_model("claude-sonnet-4-5-20250929") == "claude-sonnet-4-5-20250929"
    assert canonical_sidecar_model("claude-haiku-5-5") == "claude-haiku-5-5"
    assert canonical_sidecar_model("claude-sonnet-5-50") == "claude-sonnet-5-50"
    assert canonical_sidecar_model("claude-opus-4-7-thinking-high") == "claude-opus-4-7-thinking-high"


def test_canonical_sidecar_model_does_not_restore_a_missing_claude_prefix() -> None:
    assert canonical_sidecar_model("opus-4-7") == "opus-4-7"
    assert canonical_sidecar_model("fable-5") == "fable-5"


def test_is_known_claude_sidecar_model_accepts_wire_and_prefixed_ids() -> None:
    assert is_known_claude_sidecar_model("claude-opus-4-7") is True
    assert is_known_claude_sidecar_model("cp-claude-opus-4-7") is True
    assert is_known_claude_sidecar_model("claude-opus-4-7-thinking-high") is False
    assert is_known_claude_sidecar_model("gpt-5.4") is False


def test_apply_sidecar_model_profile_forwards_the_routed_id() -> None:
    models = (
        "claude-opus-4-7-thinking-high",
        "claude-fable-5-1-thinking-max",
        "claude-fable-5.1",
        "claude-opus-5-5-thinking-max",
        "cc/claude-opus-5.5",
        "claude-opus-5-5-20260922",
        "cc/claude-opus-5",
        "claude-sonnet-5-5-thinking-max",
        "cc/claude-sonnet-5.5",
        "claude-sonnet-5-5-20260928",
        "cc/claude-sonnet-5",
        "claude-haiku-5-5-thinking-high",
        "claude-sonnet-5-50",
        "claude-sonnet-4-5-20250929",
    )
    for model in models:
        body: dict[str, JsonValue] = {}
        wire_model = apply_sidecar_model_profile(body, stripped_model=model)
        assert wire_model == model
        assert body["model"] == model
        assert "reasoning_effort" not in body


def test_apply_sidecar_model_profile_preserves_existing_reasoning_effort() -> None:
    body = {"reasoning_effort": "medium"}

    apply_sidecar_model_profile(body, stripped_model="claude-opus-4-7-high")

    assert body["model"] == "claude-opus-4-7-high"
    assert body["reasoning_effort"] == "medium"


def test_sidecar_prefixed_model_ids_include_custom_alias_variants() -> None:
    config = _config(prefixes=("cp-", "claude"))

    assert sidecar_prefixed_model_ids("claude-opus-4-7", config) == (
        "claude-opus-4-7",
        "cp-claude-opus-4-7",
        "cp_claude-opus-4-7",
    )
