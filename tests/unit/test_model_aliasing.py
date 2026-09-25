from __future__ import annotations

from app.core.types import JsonValue
from app.modules.proxy.model_aliasing import (
    append_discoverable_alias_models,
    build_discoverable_alias_model_entries,
    resolve_model_alias,
    resolve_model_alias_pool,
)
from app.modules.settings.model_alias_pools import ModelAliasPool


def _pool(*targets: str) -> ModelAliasPool:
    return ModelAliasPool(targets=targets)


def _registry_entry(model_id: str) -> dict[str, JsonValue]:
    return {
        "id": model_id,
        "created": 1,
        "owned_by": "codex-lb",
        "api_types": ["chat_completions"],
        "context_length": 272000,
        "contextLength": 272000,
        "capabilities": {"context_length": 272000},
    }


def test_resolve_model_alias_case_insensitive() -> None:
    aliases = {"Custom_R1": _pool("cc/claude-opus-4-8")}
    assert resolve_model_alias("custom_r1", aliases) == "cc/claude-opus-4-8"
    assert resolve_model_alias("gpt-5.4", aliases) == "gpt-5.4"


def test_resolve_model_alias_returns_pool_primary() -> None:
    aliases = {"pooled/glm": _pool("or/z-ai/glm-5.3", "orca/glm-5.3")}
    assert resolve_model_alias("pooled/glm", aliases) == "or/z-ai/glm-5.3"


def test_resolve_model_alias_pool_exposes_every_target_in_order() -> None:
    aliases = {"pooled/glm": _pool("or/z-ai/glm-5.3", "orca/glm-5.3", "nv/glm-5.3")}

    resolved = resolve_model_alias_pool("POOLED/GLM", aliases)

    assert resolved is not None
    assert resolved.requested == "POOLED/GLM"
    assert resolved.alias == "pooled/glm"
    assert resolved.targets == ("or/z-ai/glm-5.3", "orca/glm-5.3", "nv/glm-5.3")
    assert resolved.primary == "or/z-ai/glm-5.3"
    assert resolved.is_pool is True


def test_resolve_model_alias_pool_unaliased_model_is_its_own_single_target() -> None:
    resolved = resolve_model_alias_pool("gpt-5.4", {"other": _pool("x")})

    assert resolved is not None
    assert resolved.alias is None
    assert resolved.targets == ("gpt-5.4",)
    assert resolved.is_pool is False


def test_resolve_model_alias_pool_single_target_alias_is_not_a_pool() -> None:
    resolved = resolve_model_alias_pool("custom_r1", {"custom_r1": _pool("cc/claude")})

    assert resolved is not None
    assert resolved.alias == "custom_r1"
    assert resolved.targets == ("cc/claude",)
    assert resolved.is_pool is False


def test_resolve_model_alias_pool_none_passthrough() -> None:
    assert resolve_model_alias_pool(None, {"a": _pool("b")}) is None
    assert resolve_model_alias(None, {"a": _pool("b")}) is None


def test_build_discoverable_alias_model_entries_copies_target_metadata() -> None:
    target = "cohere/command-r-plus"
    existing = {target: _registry_entry(target)}

    entries = build_discoverable_alias_model_entries(
        {"north-mini-code": _pool(target)},
        existing,
        created=99,
        is_target_visible=lambda _model: True,
        default_entry_fields=lambda: {"context_length": 200000},
    )

    assert len(entries) == 1
    entry = entries[0]
    assert entry["id"] == "north-mini-code"
    assert entry["created"] == 99
    assert entry["owned_by"] == "codex-lb"
    assert entry["context_length"] == 272000
    assert entry["capabilities"] == {"context_length": 272000}


def test_build_discoverable_alias_model_entries_uses_defaults_for_unknown_target() -> None:
    entries = build_discoverable_alias_model_entries(
        {"north-mini-code": _pool("or/cohere/north-mini-code")},
        {},
        created=42,
        is_target_visible=lambda _model: True,
        default_entry_fields=lambda: {
            "context_length": 200000,
            "capabilities": {"context_length": 200000},
        },
    )

    assert entries == [
        {
            "api_types": ["chat_completions"],
            "context_length": 200000,
            "capabilities": {"context_length": 200000},
            "id": "north-mini-code",
            "created": 42,
            "owned_by": "codex-lb",
        }
    ]


def test_build_discoverable_alias_model_entries_skips_existing_ids_case_insensitively() -> None:
    existing = {"North-Mini-Code": _registry_entry("North-Mini-Code")}

    entries = build_discoverable_alias_model_entries(
        {"north-mini-code": _pool("cohere/command-r-plus")},
        existing,
        created=1,
        is_target_visible=lambda _model: True,
        default_entry_fields=lambda: {"context_length": 200000},
    )

    assert entries == []


def test_build_discoverable_alias_model_entries_respects_target_visibility() -> None:
    entries = build_discoverable_alias_model_entries(
        {"north-mini-code": _pool("hidden/target")},
        {},
        created=1,
        is_target_visible=lambda model: model != "hidden/target",
        default_entry_fields=lambda: {"context_length": 200000},
    )

    assert entries == []


def test_build_discoverable_alias_model_entries_pool_listed_when_any_target_visible() -> None:
    entries = build_discoverable_alias_model_entries(
        {"pooled/glm": _pool("hidden/target", "visible/target")},
        {},
        created=1,
        is_target_visible=lambda model: model == "visible/target",
        default_entry_fields=lambda: {"context_length": 200000},
    )

    assert [entry["id"] for entry in entries] == ["pooled/glm"]


def test_build_discoverable_alias_model_entries_pool_hidden_when_no_target_visible() -> None:
    entries = build_discoverable_alias_model_entries(
        {"pooled/glm": _pool("hidden/a", "hidden/b")},
        {},
        created=1,
        is_target_visible=lambda _model: False,
        default_entry_fields=lambda: {"context_length": 200000},
    )

    assert entries == []


def test_build_discoverable_alias_model_entries_pool_clones_first_present_target() -> None:
    second = _registry_entry("orca/glm-5.3")
    second["context_length"] = 131072
    existing = {"orca/glm-5.3": second}

    entries = build_discoverable_alias_model_entries(
        {"pooled/glm": _pool("or/z-ai/glm-5.3", "orca/glm-5.3")},
        existing,
        created=5,
        is_target_visible=lambda _model: True,
        default_entry_fields=lambda: {"context_length": 200000},
    )

    assert len(entries) == 1
    assert entries[0]["id"] == "pooled/glm"
    assert entries[0]["context_length"] == 131072


def test_append_discoverable_alias_models_preserves_existing_items() -> None:
    items = [_registry_entry("gpt-5.4")]

    augmented = append_discoverable_alias_models(
        items,
        {"alias-gpt": _pool("gpt-5.4")},
        created=7,
        is_target_visible=lambda _model: True,
        default_entry_fields=lambda: {"context_length": 200000},
    )

    assert [entry["id"] for entry in augmented] == ["gpt-5.4", "alias-gpt"]
