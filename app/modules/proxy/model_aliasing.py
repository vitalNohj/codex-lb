"""User-configurable model aliasing.

A request may use an alias model name (e.g. ``custom_r1``) that resolves to
one or more real upstream model ids (e.g. ``cc/claude``). Resolving the alias
to the real model *before* sidecar routing means the prefix/full-model
matchers and the forwarded upstream model both operate on the real id, exactly
as if the client had sent it directly.

An alias with two or more targets is a *pool*: ``POST /v1/chat/completions``
tries the targets in order and fails over on retryable upstream failures (see
``alias_pool_dispatch.py``). Every other entry point uses the first target.

Configured aliases are also advertised on ``GET /v1/models`` so discovery-only
clients (for example Hermes) can select a neutral alias id instead of a
provider-prefixed model name that the client may mis-route locally.

The alias map is stored on ``DashboardSettings.model_aliases_json`` as
    ``{alias: {"targets": [real_model, ...]}}`` and is edited from the
dashboard Routing settings.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import cast

from app.core.config.settings_cache import get_settings_cache
from app.core.types import JsonValue
from app.core.utils.request_id import get_request_id
from app.modules.settings.model_alias_pools import ModelAliasPool, find_alias_pool
from app.modules.settings.service import parse_model_aliases

logger = logging.getLogger(__name__)

DiscoverableAliasEntryFields = Callable[[], dict[str, JsonValue]]
TargetVisibility = Callable[[str], bool]


@dataclass(frozen=True, slots=True)
class ResolvedModelAlias:
    """What a requested model name resolved to.

    ``alias`` is the alias as configured (``None`` when the request named a
    real model), ``targets`` is the ordered candidate list. An unaliased model
    resolves to itself as the only target.
    """

    requested: str
    alias: str | None
    targets: tuple[str, ...]

    @property
    def primary(self) -> str:
        return self.targets[0]

    @property
    def is_pool(self) -> bool:
        return self.alias is not None and len(self.targets) > 1


def resolve_model_alias(model: str | None, aliases: Mapping[str, ModelAliasPool]) -> str | None:
    """Return the primary real model for ``model`` or ``model`` itself when unaliased.

    Matching is case-insensitive on the alias key. ``None`` in -> ``None`` out.
    Single-target callers (Responses, catalog, pricing) use this; the chat path
    uses :func:`resolve_model_alias_pool` to see every target.
    """

    resolved = resolve_model_alias_pool(model, aliases)
    return resolved.primary if resolved is not None else None


def resolve_model_alias_pool(model: str | None, aliases: Mapping[str, ModelAliasPool]) -> ResolvedModelAlias | None:
    """Resolve ``model`` to its ordered targets; unaliased models map to themselves."""

    if model is None:
        return None
    normalized = model.strip()
    if not normalized:
        return ResolvedModelAlias(requested=model, alias=None, targets=(model,))
    found = find_alias_pool(normalized, aliases)
    if found is None:
        return ResolvedModelAlias(requested=model, alias=None, targets=(model,))
    alias, pool = found
    return ResolvedModelAlias(requested=model, alias=alias, targets=pool.targets)


async def load_model_aliases() -> dict[str, ModelAliasPool]:
    try:
        dashboard_settings = await get_settings_cache().get()
    except Exception:
        logger.warning("failed to load dashboard settings for model aliasing", exc_info=True)
        return {}
    return parse_model_aliases(dashboard_settings.model_aliases_json)


async def resolve_request_model_alias(model: str | None) -> str | None:
    """Resolve ``model`` to its primary target, logging rewrites.

    Entry points without failover (Responses) use this; it is the pre-pool
    behavior exactly.
    """

    resolved = await resolve_request_model_alias_pool(model)
    return resolved.primary if resolved is not None else None


async def resolve_request_model_alias_pool(model: str | None) -> ResolvedModelAlias | None:
    """Resolve ``model`` against the configured alias map, logging rewrites."""

    aliases = await load_model_aliases()
    resolved = resolve_model_alias_pool(model, aliases)
    if resolved is not None and resolved.alias is not None:
        logger.info(
            "model_alias_resolved request_id=%s requested_model=%s resolved_model=%s targets=%d",
            get_request_id(),
            model,
            resolved.primary,
            len(resolved.targets),
        )
    return resolved


def _existing_model_ids_lower(existing_entries: Mapping[str, Mapping[str, JsonValue]]) -> set[str]:
    return {model_id.lower() for model_id in existing_entries}


def build_discoverable_alias_model_entries(
    aliases: Mapping[str, ModelAliasPool],
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
    id (case-insensitive). An alias is listed when any of its targets is
    visible for the requesting API key; its metadata is cloned from the first
    target, in pool order, that is present in ``existing_entries``.
    """

    if not aliases:
        return []

    reserved_ids = _existing_model_ids_lower(existing_entries)
    entries: list[dict[str, JsonValue]] = []

    for alias, pool in aliases.items():
        normalized_alias = alias.strip()
        if not normalized_alias or not pool.targets:
            continue
        if normalized_alias.lower() in reserved_ids:
            continue
        visible_targets = [target for target in pool.targets if is_target_visible(target)]
        if not visible_targets:
            continue

        target_entry: Mapping[str, JsonValue] | None = None
        for target in pool.targets:
            candidate = existing_entries.get(target)
            if candidate is not None:
                target_entry = candidate
                break
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
    aliases: Mapping[str, ModelAliasPool],
    *,
    created: int,
    is_target_visible: TargetVisibility,
    default_entry_fields: DiscoverableAliasEntryFields,
) -> list[dict[str, JsonValue]]:
    """Return ``items`` plus any discoverable alias entries not already present."""

    existing_entries = {str(entry["id"]): entry for entry in items if isinstance(entry.get("id"), str)}
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
