from __future__ import annotations

from app.core.clients.claude_sidecar import ClaudeSidecarConfig
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
        model_prefixes=prefixes,
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )


def test_canonical_sidecar_model_strips_cp_prefix_via_pricing_alias() -> None:
    assert canonical_sidecar_model("cp-claude-opus-4-7") == "claude-opus-4-7"
    assert canonical_sidecar_model("cp-claude-opus-4-8") == "claude-opus-4-8"
    assert canonical_sidecar_model("cp-claude-fable-5") == "claude-fable-5"


def test_canonical_sidecar_model_restores_claude_family_prefix() -> None:
    assert canonical_sidecar_model("opus-4-7") == "claude-opus-4-7"
    assert canonical_sidecar_model("fable-5") == "claude-fable-5"


def test_is_known_claude_sidecar_model_accepts_wire_and_prefixed_ids() -> None:
    assert is_known_claude_sidecar_model("claude-opus-4-7") is True
    assert is_known_claude_sidecar_model("cp-claude-opus-4-7") is True
    assert is_known_claude_sidecar_model("claude-opus-4-7-thinking-high") is True
    assert is_known_claude_sidecar_model("gpt-5.4") is False


def test_apply_sidecar_model_profile_resolves_cursor_thinking_suffix() -> None:
    body: dict[str, object] = {}
    wire_model = apply_sidecar_model_profile(
        body,
        stripped_model="claude-opus-4-7-thinking-high",
    )

    assert wire_model == "claude-opus-4-7"
    assert body["model"] == "claude-opus-4-7"
    assert body["reasoning_effort"] == "high"


def test_apply_sidecar_model_profile_preserves_existing_reasoning_effort() -> None:
    body = {"reasoning_effort": "medium"}

    apply_sidecar_model_profile(body, stripped_model="claude-opus-4-7-high")

    assert body["model"] == "claude-opus-4-7"
    assert body["reasoning_effort"] == "medium"


def test_apply_sidecar_model_profile_preserves_date_suffixed_wire_model() -> None:
    body: dict[str, object] = {}

    wire_model = apply_sidecar_model_profile(body, stripped_model="claude-sonnet-4-5-20250929")

    assert wire_model == "claude-sonnet-4-5-20250929"
    assert body["model"] == "claude-sonnet-4-5-20250929"


def test_sidecar_prefixed_model_ids_include_custom_alias_variants() -> None:
    config = _config(prefixes=("cp-", "claude"))

    assert sidecar_prefixed_model_ids("claude-opus-4-7", config) == (
        "claude-opus-4-7",
        "cp-claude-opus-4-7",
        "cp_claude-opus-4-7",
    )
