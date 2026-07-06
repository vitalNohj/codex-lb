"""Catalog metadata overlays for dashboard-configured custom model aliases.

Custom aliases are client-facing model ids configured in dashboard settings.
This module applies optional discovery metadata (for example an advertised
``context_length`` on ``GET /v1/models``) to alias catalog entries only.

Request-time alias resolution lives in ``model_aliasing.py``; sidecar routing is
unchanged. Future catalog fields can be added here without coupling to a
specific provider integration.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import cast

from app.core.config.settings_cache import get_settings_cache
from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping
from app.modules.settings.service import parse_custom_alias_catalog, parse_model_aliases

logger = logging.getLogger(__name__)

PRESET_CONTEXT_LENGTHS: tuple[int, ...] = (128_000, 200_000, 1_000_000)


@dataclass(frozen=True, slots=True)
class CustomAliasCatalogEntry:
    context_length: int | None = None


def reconcile_custom_alias_catalog(
    catalog: Mapping[str, Mapping[str, int]],
    aliases: Mapping[str, str],
) -> dict[str, dict[str, int]]:
    """Drop catalog rows that are not configured aliases or lack a context length."""

    if not catalog or not aliases:
        return {}

    alias_keys = {alias.strip().lower() for alias in aliases if alias.strip()}
    reconciled: dict[str, dict[str, int]] = {}
    for alias, entry in catalog.items():
        normalized_alias = alias.strip()
        if not normalized_alias or normalized_alias.lower() not in alias_keys:
            continue
        context_length = entry.get("context_length", entry.get("contextLength"))
        if not isinstance(context_length, int) or isinstance(context_length, bool) or context_length <= 0:
            continue
        reconciled[normalized_alias] = {"context_length": context_length}
    return reconciled


def filter_custom_alias_catalog_for_aliases(
    catalog: Mapping[str, CustomAliasCatalogEntry],
    aliases: Mapping[str, str],
) -> dict[str, CustomAliasCatalogEntry]:
    """Keep only catalog rows keyed by configured alias ids."""

    if not catalog or not aliases:
        return {}

    alias_keys = {alias.strip().lower() for alias in aliases if alias.strip()}
    filtered: dict[str, CustomAliasCatalogEntry] = {}
    for alias, entry in catalog.items():
        normalized_alias = alias.strip()
        if not normalized_alias or normalized_alias.lower() not in alias_keys:
            continue
        if entry.context_length is None:
            continue
        filtered[normalized_alias] = entry
    return filtered


async def load_custom_alias_catalog() -> dict[str, CustomAliasCatalogEntry]:
    try:
        dashboard_settings = await get_settings_cache().get()
    except Exception:
        logger.warning("failed to load dashboard settings for custom alias catalog", exc_info=True)
        return {}
    aliases = parse_model_aliases(dashboard_settings.model_aliases_json)
    raw_catalog = parse_custom_alias_catalog(dashboard_settings.custom_alias_catalog_json)
    catalog = {
        alias: CustomAliasCatalogEntry(context_length=entry.get("context_length"))
        for alias, entry in raw_catalog.items()
    }
    return filter_custom_alias_catalog_for_aliases(catalog, aliases)


def _set_advertised_context_length(entry: MutableMapping[str, JsonValue], context_length: int) -> None:
    entry["context_length"] = context_length
    entry["contextLength"] = context_length
    capabilities = entry.get("capabilities")
    if is_json_mapping(capabilities):
        capabilities_dict = dict(cast(dict[str, JsonValue], capabilities))
    else:
        capabilities_dict = {}
    capabilities_dict["context_length"] = context_length
    entry["capabilities"] = capabilities_dict
    metadata = entry.get("metadata")
    if is_json_mapping(metadata):
        metadata_dict = dict(cast(dict[str, JsonValue], metadata))
        metadata_dict["context_window"] = context_length
        metadata_dict["input_context_window"] = context_length
        entry["metadata"] = metadata_dict


def apply_custom_alias_catalog_entry(
    entry: Mapping[str, JsonValue],
    catalog_entry: CustomAliasCatalogEntry,
) -> dict[str, JsonValue]:
    """Return ``entry`` with any configured alias catalog overlays applied."""

    patched = dict(entry)
    if catalog_entry.context_length is not None:
        _set_advertised_context_length(patched, catalog_entry.context_length)
    return patched


def apply_custom_alias_catalog_overrides(
    entries: list[dict[str, JsonValue]],
    catalog: Mapping[str, CustomAliasCatalogEntry],
) -> list[dict[str, JsonValue]]:
    """Apply catalog overlays to alias rows in a serialized ``/v1/models`` list."""

    if not catalog:
        return entries

    catalog_by_lower = {alias.lower(): (alias, entry) for alias, entry in catalog.items()}
    patched: list[dict[str, JsonValue]] = []
    for entry in entries:
        model_id = entry.get("id")
        if not isinstance(model_id, str):
            patched.append(entry)
            continue
        catalog_match = catalog_by_lower.get(model_id.lower())
        if catalog_match is None:
            patched.append(entry)
            continue
        _, catalog_entry = catalog_match
        patched.append(apply_custom_alias_catalog_entry(entry, catalog_entry))
    return patched
