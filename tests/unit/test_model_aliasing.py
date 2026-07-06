from __future__ import annotations

from app.modules.proxy.model_aliasing import (
    append_discoverable_alias_models,
    build_discoverable_alias_model_entries,
    resolve_model_alias,
)


def _registry_entry(model_id: str) -> dict[str, object]:
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
    aliases = {"Custom_R1": "cc/claude-opus-4-8"}
    assert resolve_model_alias("custom_r1", aliases) == "cc/claude-opus-4-8"
    assert resolve_model_alias("gpt-5.4", aliases) == "gpt-5.4"


def test_build_discoverable_alias_model_entries_copies_target_metadata() -> None:
    target = "cohere/command-r-plus"
    existing = {target: _registry_entry(target)}

    entries = build_discoverable_alias_model_entries(
        {"north-mini-code": target},
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
        {"north-mini-code": "or/cohere/north-mini-code"},
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
        {"north-mini-code": "cohere/command-r-plus"},
        existing,
        created=1,
        is_target_visible=lambda _model: True,
        default_entry_fields=lambda: {"context_length": 200000},
    )

    assert entries == []


def test_build_discoverable_alias_model_entries_respects_target_visibility() -> None:
    entries = build_discoverable_alias_model_entries(
        {"north-mini-code": "hidden/target"},
        {},
        created=1,
        is_target_visible=lambda model: model != "hidden/target",
        default_entry_fields=lambda: {"context_length": 200000},
    )

    assert entries == []


def test_append_discoverable_alias_models_preserves_existing_items() -> None:
    items = [_registry_entry("gpt-5.4")]

    augmented = append_discoverable_alias_models(
        items,
        {"alias-gpt": "gpt-5.4"},
        created=7,
        is_target_visible=lambda _model: True,
        default_entry_fields=lambda: {"context_length": 200000},
    )

    assert [entry["id"] for entry in augmented] == ["gpt-5.4", "alias-gpt"]
