"""Unified sidecar model routing.

A single, provider-agnostic resolver decides which sidecar integration owns a
model and what wire model to forward. Resolution proceeds in two passes:

1. **Full model name pass** -- case-insensitive exact match against any enabled
   integration's full-model list. The wire model is forwarded unchanged (never
   stripped).
2. **Prefix pass** -- longest matching configured prefix across all enabled
   integrations. The matched prefix is removed from the wire model only when the
   prefix's strip flag is set.

Cross-integration uniqueness (enforced on save) guarantees at most one owner per
prefix/full-model value; the provider order below is a deterministic tiebreak
that uniqueness makes unreachable in practice.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.core.clients.claude_sidecar import SidecarPrefix

# Deterministic tiebreak order. Lower index wins.
SIDECAR_PROVIDER_ORDER: tuple[str, ...] = ("claude", "openrouter", "omniroute", "ollama")


@dataclass(frozen=True, slots=True)
class SidecarRoutingEntry:
    """One enabled integration's routing inputs."""

    provider: str
    prefixes: tuple[SidecarPrefix, ...]
    full_models: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SidecarRoutingDecision:
    provider: str
    wire_model: str


def _provider_rank(provider: str) -> int:
    try:
        return SIDECAR_PROVIDER_ORDER.index(provider)
    except ValueError:
        return len(SIDECAR_PROVIDER_ORDER)


def prefix_variants(prefix: str) -> tuple[str, ...]:
    """Return interchangeable ``-``/``_`` variants for a normalized prefix."""

    normalized = prefix.strip().lower()
    if not normalized:
        return ()
    if normalized.endswith("-"):
        return (normalized, f"{normalized[:-1]}_")
    if normalized.endswith("_"):
        return (normalized, f"{normalized[:-1]}-")
    return (normalized,)


def resolve_sidecar_route(
    model: str,
    entries: tuple[SidecarRoutingEntry, ...],
) -> SidecarRoutingDecision | None:
    """Resolve the owning integration and wire model for ``model``.

    ``entries`` must contain only enabled integrations.
    """

    normalized = model.strip()
    if not normalized:
        return None
    lowered = normalized.lower()

    # Pass 1: full model name exact match (case-insensitive), forwarded as-is.
    full_match: SidecarRoutingEntry | None = None
    for entry in entries:
        if any(lowered == full.strip().lower() for full in entry.full_models):
            if full_match is None or _provider_rank(entry.provider) < _provider_rank(full_match.provider):
                full_match = entry
    if full_match is not None:
        return SidecarRoutingDecision(provider=full_match.provider, wire_model=normalized)

    # Pass 2: longest matching prefix across all integrations.
    best_entry: SidecarRoutingEntry | None = None
    best_prefix: SidecarPrefix | None = None
    best_variant: str = ""
    for entry in entries:
        for prefix in entry.prefixes:
            for variant in prefix_variants(prefix.prefix):
                if not lowered.startswith(variant):
                    continue
                better_length = len(variant) > len(best_variant)
                tie = len(variant) == len(best_variant) and (
                    best_entry is None or _provider_rank(entry.provider) < _provider_rank(best_entry.provider)
                )
                if best_entry is None or better_length or tie:
                    best_entry = entry
                    best_prefix = prefix
                    best_variant = variant
    if best_entry is None or best_prefix is None:
        return None

    wire_model = normalized
    if best_prefix.strip:
        wire_model = normalized[len(best_variant) :].strip() or normalized
    return SidecarRoutingDecision(provider=best_entry.provider, wire_model=wire_model)


def parse_sidecar_prefixes(raw: str | None) -> tuple[SidecarPrefix, ...]:
    """Parse stored ``[{"prefix": str, "strip": bool}, ...]`` JSON.

    Only the object shape is accepted; the migration normalizes legacy string
    arrays into this shape.
    """

    if not raw:
        return ()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, list):
        return ()
    prefixes: list[SidecarPrefix] = []
    seen: set[str] = set()
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        value = entry.get("prefix")
        if not isinstance(value, str):
            continue
        normalized = value.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        prefixes.append(SidecarPrefix(prefix=normalized, strip=bool(entry.get("strip", False))))
    return tuple(prefixes)


def parse_sidecar_full_models(raw: str | None) -> tuple[str, ...]:
    """Parse stored ``[str, ...]`` full-model JSON."""

    if not raw:
        return ()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, list):
        return ()
    models: list[str] = []
    seen: set[str] = set()
    for entry in parsed:
        if not isinstance(entry, str):
            continue
        normalized = entry.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        models.append(normalized)
    return tuple(models)
