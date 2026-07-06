from __future__ import annotations

from app.modules.proxy.custom_alias_catalog import (
    CustomAliasCatalogEntry,
    apply_custom_alias_catalog_entry,
    apply_custom_alias_catalog_overrides,
    filter_custom_alias_catalog_for_aliases,
    reconcile_custom_alias_catalog,
)


def test_reconcile_custom_alias_catalog_drops_orphans_and_empty_rows() -> None:
    catalog = {
        "alias-a": {"context_length": 1_000_000},
        "orphan": {"context_length": 200_000},
        "alias-b": {},
    }
    aliases = {"alias-a": "gpt-5.4", "alias-c": "gpt-5.5"}

    reconciled = reconcile_custom_alias_catalog(catalog, aliases)

    assert reconciled == {"alias-a": {"context_length": 1_000_000}}


def test_filter_custom_alias_catalog_for_aliases_keeps_only_configured_aliases() -> None:
    catalog = {
        "alias-a": CustomAliasCatalogEntry(context_length=128_000),
        "orphan": CustomAliasCatalogEntry(context_length=200_000),
        "alias-b": CustomAliasCatalogEntry(context_length=None),
    }
    aliases = {"alias-a": "gpt-5.4"}

    filtered = filter_custom_alias_catalog_for_aliases(catalog, aliases)

    assert filtered == {"alias-a": CustomAliasCatalogEntry(context_length=128_000)}


def test_apply_custom_alias_catalog_entry_patches_context_fields() -> None:
    entry = {
        "id": "north-mini-code",
        "context_length": 272_000,
        "capabilities": {"context_length": 272_000},
        "metadata": {"context_window": 272_000, "input_context_window": 272_000},
    }

    patched = apply_custom_alias_catalog_entry(
        entry,
        CustomAliasCatalogEntry(context_length=1_000_000),
    )

    assert patched["context_length"] == 1_000_000
    assert patched["contextLength"] == 1_000_000
    assert patched["capabilities"] == {"context_length": 1_000_000}
    assert patched["metadata"] == {
        "context_window": 1_000_000,
        "input_context_window": 1_000_000,
    }


def test_apply_custom_alias_catalog_overrides_matches_case_insensitively() -> None:
    entries = [
        {"id": "Alias-GPT", "context_length": 272_000},
        {"id": "gpt-5.4", "context_length": 272_000},
    ]
    catalog = {"alias-gpt": CustomAliasCatalogEntry(context_length=1_000_000)}

    patched = apply_custom_alias_catalog_overrides(entries, catalog)

    assert patched[0]["context_length"] == 1_000_000
    assert patched[1]["context_length"] == 272_000
