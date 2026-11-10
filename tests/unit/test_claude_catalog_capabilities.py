from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.clients.claude_sidecar import ClaudeSidecarConfig
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.core.types import JsonValue
from app.core.usage import pricing_catalog as catalog
from app.core.usage.model_capabilities import ModelCapabilities, parse_models_dev_capabilities
from app.modules.proxy import claude_sidecar_dispatch as dispatch
from app.modules.proxy.sidecar_model_capabilities import sidecar_input_modalities, sidecar_supports_vision

pytestmark = pytest.mark.unit


@pytest.fixture
def capabilities(monkeypatch):
    payload = json.loads((Path(__file__).parents[1] / "fixtures" / "claude_models_dev.json").read_text())
    parsed = parse_models_dev_capabilities(payload)
    monkeypatch.setattr(catalog, "_capabilities", parsed)
    return parsed


@pytest.mark.parametrize("prefix", ["", "cc/", "cp-", "cp_"])
@pytest.mark.parametrize("field", ["max_tokens", "max_completion_tokens"])
@pytest.mark.parametrize("requested,expected", [(4096, 32_768), (200_000, 128_000), (1, 1), (16, 16)])
def test_catalog_model_without_fixed_row_uses_output_bounds(capabilities, prefix, field, requested, expected):
    assert "claude-fable-5-2" not in dispatch._SIDECAR_MAX_TOKENS_BOUNDS
    body: dict[str, JsonValue] = {field: requested}
    dispatch.apply_sidecar_max_tokens_bounds(body, wire_model=prefix + "claude-fable-5-2")
    assert body == {field: expected}
    assert dispatch.claude_sidecar_context_window(prefix + "claude-fable-5-2") == 1_000_000


def test_chat_payload_keeps_exact_model_and_uses_catalog_floor(capabilities):
    config = ClaudeSidecarConfig(
        enabled=True,
        base_url="http://127.0.0.1:8317",
        api_key="key",
        prefixes=(),
        connect_timeout_seconds=8,
        request_timeout_seconds=600,
        models_cache_ttl_seconds=60,
    )
    payload = ChatCompletionsRequest.model_validate(
        {"model": "claude-fable-5-2", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 4096}
    )
    forwarded = dispatch.build_sidecar_chat_payload(payload, "claude-fable-5-2", config)
    assert forwarded.body["model"] == "claude-fable-5-2"
    assert forwarded.body["max_tokens"] == 32_768


@pytest.mark.parametrize("requested,expected", [(4096, 12_000), (16_000, 16_000)])
def test_catalog_context_guard_only_lowers_the_raise(capabilities, requested, expected):
    body: dict[str, JsonValue] = {"max_tokens": requested, "messages": [{"role": "user", "content": "hello"}]}
    context = dispatch._estimate_sidecar_input_tokens(body) + 12_000
    catalog.install_model_capabilities({"claude-fable-5-2": ModelCapabilities(context_window=context)})
    dispatch.apply_sidecar_max_tokens_bounds(body, wire_model="claude-fable-5-2")
    assert body["max_tokens"] == expected


@pytest.mark.parametrize("model,bounds", dispatch._SIDECAR_MAX_TOKENS_BOUNDS.items())
def test_fixed_bounds_win_over_conflicting_catalog(capabilities, model, bounds):
    catalog.install_model_capabilities({model: ModelCapabilities(("text",), 2_000, 1_000)})
    body: dict[str, JsonValue] = {"max_tokens": 4096, "max_completion_tokens": 999_999}
    dispatch.apply_sidecar_max_tokens_bounds(body, wire_model="cc/" + model)
    assert body == {"max_tokens": min(bounds.floor, bounds.cap), "max_completion_tokens": bounds.cap}
    assert dispatch.claude_sidecar_context_window(model) == bounds.context_window


@pytest.mark.parametrize(
    "model",
    [
        "claude-unreleased-9",
        "claude-fable-5.2",
        "claude-fable-5-2-20261109",
        "claude-fable-5-2-thinking-max",
        "cc/cc/claude-fable-5-2",
    ],
)
def test_unlisted_exact_id_stays_unchanged(capabilities, model):
    body: dict[str, JsonValue] = {"max_tokens": 4096, "max_completion_tokens": 999_999}
    dispatch.apply_sidecar_max_tokens_bounds(body, wire_model=model)
    assert body == {"max_tokens": 4096, "max_completion_tokens": 999_999}
    assert dispatch.claude_sidecar_context_window(model) is None
    assert sidecar_input_modalities(None, claude_model=model) == ["text"]
    assert sidecar_supports_vision(None, claude_model=model) is False


@pytest.mark.parametrize("metadata", [ModelCapabilities(), ModelCapabilities(context_window=1_000_000)])
def test_incomplete_limits_do_not_create_bounds_or_vision(capabilities, metadata):
    capabilities["claude-future"] = metadata
    body: dict[str, JsonValue] = {"max_tokens": 4096}
    dispatch.apply_sidecar_max_tokens_bounds(body, wire_model="claude-future")
    assert body == {"max_tokens": 4096}
    assert sidecar_supports_vision(None, claude_model="claude-future") is False


def test_catalog_absent_keeps_prior_unknown_and_fixed_behavior(monkeypatch):
    monkeypatch.setattr(catalog, "_capabilities", {})
    for model, expected in (("claude-fable-5-2", 4096), ("claude-fable-5-1", 32_768)):
        body: dict[str, JsonValue] = {"max_tokens": 4096}
        dispatch.apply_sidecar_max_tokens_bounds(body, wire_model=model)
        assert body == {"max_tokens": expected}
    assert dispatch.claude_sidecar_context_window("claude-fable-5-2") is None
    assert sidecar_supports_vision(None, claude_model="claude-fable-5-2") is False
    assert sidecar_supports_vision(None, claude_model="claude-fable-5-1") is True


def test_catalog_modalities_win_and_limits_alone_do_not_imply_vision(capabilities):
    assert sidecar_input_modalities({"input_modalities": ["text"]}, claude_model="claude-fable-5-2") == [
        "text",
        "image",
        "pdf",
    ]
    catalog.install_model_capabilities({"claude-fable-5-2": ModelCapabilities(("text",))})
    assert sidecar_supports_vision({"input_modalities": ["text", "image"]}, claude_model="claude-fable-5-2") is False
    catalog.install_model_capabilities(
        {"claude-limits-only": ModelCapabilities(context_window=1_000_000, max_output_tokens=128_000)}
    )
    assert dispatch.claude_sidecar_context_window("claude-limits-only") == 1_000_000
    assert sidecar_supports_vision(None, claude_model="claude-limits-only") is False


def test_absent_output_fields_stay_absent(capabilities):
    body: dict[str, JsonValue] = {"model": "claude-fable-5-2"}
    dispatch.apply_sidecar_max_tokens_bounds(body, wire_model="claude-fable-5-2")
    assert body == {"model": "claude-fable-5-2"}
