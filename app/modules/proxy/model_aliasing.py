"""User-configurable model aliasing.

A request may use an alias model name (e.g. ``custom_r1``) that resolves to a
real upstream model id (e.g. ``cc/claude``). Resolving the alias to the real
model *before* sidecar routing means the prefix/full-model matchers and the
forwarded upstream model both operate on the real id, exactly as if the client
had sent it directly.

Configured aliases are also advertised on ``GET /v1/models`` so discovery-only
clients (for example Hermes) can select a neutral alias id instead of a
provider-prefixed model name that the client may mis-route locally.

The alias map is stored on ``DashboardSettings.model_aliases_json`` as
    ``{alias: real_model}`` and is edited from the dashboard Routing settings.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import cast

from app.core.config.settings_cache import get_settings_cache
from app.core.types import JsonValue
from app.core.utils.request_id import get_request_id
from app.modules.settings.service import parse_model_aliases

logger = logging.getLogger(__name__)

DiscoverableAliasEntryFields = Callable[[], dict[str, JsonValue]]
TargetVisibility = Callable[[str], bool]


def resolve_model_alias(model: str | None, aliases: dict[str, str]) -> str | None:
    """Return the real model for ``model`` or ``model`` itself when unaliased.

    Matching is case-insensitive on the alias key. ``None`` in -> ``None`` out.
    """

    if model is None:
        return None
    if not aliases:
        return model
    normalized = model.strip()
    if not normalized:
        return model
    lowered = normalized.lower()
    for alias, target in aliases.items():
        if alias.strip().lower() == lowered:
            return target
    return model


async def load_model_aliases() -> dict[str, str]:
    try:
        dashboard_settings = await get_settings_cache().get()
    except Exception:
        logger.warning("failed to load dashboard settings for model aliasing", exc_info=True)
        return {}
    return parse_model_aliases(dashboard_settings.model_aliases_json)


async def resolve_request_model_alias(model: str | None) -> str | None:
    """Resolve ``model`` against the configured alias map, logging rewrites."""

    aliases = await load_model_aliases()
    resolved = resolve_model_alias(model, aliases)
    if resolved is not None and model is not None and resolved != model:
        logger.info(
            "model_alias_resolved request_id=%s requested_model=%s resolved_model=%s",
            get_request_id(),
            model,
            resolved,
        )
    return resolved


def _existing_model_ids_lower(existing_entries: Mapping[str, Mapping[str, JsonValue]]) -> set[str]:
    return {model_id.lower() for model_id in existing_entries}


def build_discoverable_alias_model_entries(
    aliases: Mapping[str, str],
    existing_entries: Mapping[str, Mapping[str, JsonValue]],
    *,
    created: int,
    is_target_visible: TargetVisibility,
    default_entry_fields: DiscoverableAliasEntryFields,
) -> list[dict[str, JsonValue]]:
    """Build ``/v1/models`` entries for configured aliases.

    Each alias is advertised as its own model id so discovery-only clients
    (for example Hermes) can select a neutral name that resolves to the real
    upstream model on chat requests. Aliases never override an existing catalog
    id (case-insensitive). An alias is listed when its target is visible for
    the requesting API key.
    """

    if not aliases:
        return []

    reserved_ids = _existing_model_ids_lower(existing_entries)
    entries: list[dict[str, JsonValue]] = []

    for alias, target in aliases.items():
        normalized_alias = alias.strip()
        normalized_target = target.strip()
        if not normalized_alias or not normalized_target:
            continue
        if normalized_alias.lower() in reserved_ids:
            continue
        if not is_target_visible(normalized_target):
            continue

        target_entry = existing_entries.get(normalized_target)
        if target_entry is not None:
            entry = dict(target_entry)
        else:
            entry = {
                "api_types": ["chat_completions"],
                **default_entry_fields(),
            }

        entry["id"] = normalized_alias
        entry["created"] = created
        entry["owned_by"] = "codex-lb"
        entries.append(cast(dict[str, JsonValue], entry))
        reserved_ids.add(normalized_alias.lower())

    return entries


def append_discoverable_alias_models(
    items: list[dict[str, JsonValue]],
    aliases: Mapping[str, str],
    *,
    created: int,
    is_target_visible: TargetVisibility,
    default_entry_fields: DiscoverableAliasEntryFields,
) -> list[dict[str, JsonValue]]:
    """Return ``items`` plus any discoverable alias entries not already present."""

    existing_entries = {
        str(entry["id"]): entry for entry in items if isinstance(entry.get("id"), str)
    }
    alias_entries = build_discoverable_alias_model_entries(
        aliases,
        existing_entries,
        created=created,
        is_target_visible=is_target_visible,
        default_entry_fields=default_entry_fields,
    )
    if not alias_entries:
        return items
    return [*items, *alias_entries]
