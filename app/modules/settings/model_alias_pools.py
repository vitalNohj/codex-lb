"""Model alias pools: one client-facing alias, an ordered list of real models.

The dashboard alias map is stored on ``DashboardSettings.model_aliases_json``
as ``{alias: {"targets": [model, ...]}}``. A one-target pool is the legacy
single alias; a longer pool is tried in order by the chat failover loop.

This module is the only parser/serializer for that blob so settings, routing,
pricing, and the dashboard API cannot drift. It has no app dependencies on
purpose: both the settings service and the proxy import it.

The legacy value shape ``{alias: "model"}`` is still accepted on read for one
release so a replica on the previous version and a row written by this one can
coexist during a rolling upgrade; the Alembic migration rewrites stored rows
to the pool shape.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

MAX_ALIAS_LENGTH = 256
MAX_TARGET_LENGTH = 256
MAX_POOL_TARGETS = 16


@dataclass(frozen=True, slots=True)
class ModelAliasPool:
    """Ordered targets for one alias. ``targets[0]`` is preferred."""

    targets: tuple[str, ...]

    @property
    def primary(self) -> str:
        return self.targets[0]

    @property
    def is_pool(self) -> bool:
        """Whether failover applies: two or more targets."""

        return len(self.targets) > 1


ModelAliasPools = dict[str, ModelAliasPool]


def normalize_pool_targets(raw_targets: Iterable[Any]) -> tuple[str, ...]:
    """Strip, drop blanks and non-strings, de-duplicate case-insensitively, keep order."""

    targets: list[str] = []
    seen: set[str] = set()
    for target in raw_targets:
        if not isinstance(target, str):
            continue
        normalized = target.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        targets.append(normalized)
    return tuple(targets)


def pool_from_value(value: Any) -> ModelAliasPool | None:
    """Build a pool from either stored shape; ``None`` when nothing usable."""

    if isinstance(value, str):
        targets = normalize_pool_targets((value,))
    elif isinstance(value, Mapping):
        raw_targets = value.get("targets")
        if not isinstance(raw_targets, list):
            return None
        targets = normalize_pool_targets(raw_targets)
    elif isinstance(value, ModelAliasPool):
        targets = normalize_pool_targets(value.targets)
    else:
        return None
    if not targets:
        return None
    return ModelAliasPool(targets=targets)


def normalize_alias_pools(raw: Mapping[str, Any]) -> ModelAliasPools:
    """Normalize an alias map of either value shape.

    Blank aliases and empty pools are dropped; aliases are de-duplicated
    case-insensitively with the first spelling kept.
    """

    pools: ModelAliasPools = {}
    seen: set[str] = set()
    for alias, value in raw.items():
        if not isinstance(alias, str):
            continue
        normalized_alias = alias.strip()
        if not normalized_alias:
            continue
        key = normalized_alias.lower()
        if key in seen:
            continue
        pool = pool_from_value(value)
        if pool is None:
            continue
        seen.add(key)
        pools[normalized_alias] = pool
    return pools


def parse_alias_pools_json(raw: str | None) -> ModelAliasPools:
    """Parse the stored ``model_aliases_json`` column."""

    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return normalize_alias_pools(parsed)


def dump_alias_pools_json(pools: Mapping[str, ModelAliasPool | Mapping[str, Any] | str]) -> str:
    """Serialize to the pool shape, sorted so equal maps produce equal bytes."""

    normalized = normalize_alias_pools(pools)
    payload = {alias: {"targets": list(pool.targets)} for alias, pool in normalized.items()}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def alias_pools_to_plain(pools: Mapping[str, ModelAliasPool]) -> dict[str, dict[str, list[str]]]:
    """The API/JSON shape: ``{alias: {"targets": [...]}}``."""

    return {alias: {"targets": list(pool.targets)} for alias, pool in pools.items()}


def primary_targets(pools: Mapping[str, ModelAliasPool]) -> dict[str, str]:
    """``{alias: targets[0]}`` for consumers that need one model per alias.

    Used by the pricing resolver, which rewrites an alias to a single id before
    catalog lookup; the primary is the right stand-in because a pool request is
    priced by the target that served it, not by the alias.
    """

    return {alias: pool.primary for alias, pool in pools.items()}


def find_alias_pool(model: str | None, pools: Mapping[str, ModelAliasPool]) -> tuple[str, ModelAliasPool] | None:
    """Return ``(alias_as_configured, pool)`` for ``model``, matched case-insensitively."""

    if model is None or not pools:
        return None
    normalized = model.strip()
    if not normalized:
        return None
    lowered = normalized.lower()
    for alias, pool in pools.items():
        if alias.strip().lower() == lowered:
            return alias, pool
    return None
