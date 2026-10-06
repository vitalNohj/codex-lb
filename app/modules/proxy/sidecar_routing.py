"""Unified sidecar model routing.

A single, provider-agnostic resolver decides which sidecar integration owns a
model and what wire model to forward. Resolution proceeds in two passes:

1. **Full model name pass** -- case-insensitive exact match against any enabled
   integration's full-model list. The wire model is forwarded unchanged (never
   stripped). The same full model may be configured on several integrations;
   the entry whose integration is *starred* for that model wins. When several
   enabled integrations list the model and none is starred, the bare id is
   ambiguous and stays unrouted by default -- the star names the default
   route, so without it bare requests refuse to guess and alias pools must
   target the model explicitly via ``<provider>::<model>``. A model listed by
   only one enabled integration keeps routing even starless, preserving
   pre-stars behavior for starless rows.
2. **Prefix pass** -- longest matching configured prefix across all enabled
   integrations. The matched prefix is removed from the wire model only when the
   prefix's strip flag is set.

An explicit ``<provider>::<model>`` pool target is parsed only after the
full-model pass, so a configured full-model id that itself contains ``::``
(e.g. ``openrouter::some-id``) still resolves as an exact bare model. A target
whose provider names a known integration resolves only within that
integration; when that integration is not enabled the target is unroutable
rather than falling through to bare-model matching, where another integration
could claim it. A ``::`` id whose leading segment names no known provider is
resolved like any bare model, so real model ids containing ``::`` keep
working.

Alias pools resolve their stored targets through
:func:`resolve_sidecar_pool_target` instead, which applies the explicit-target
rule *first*: a literal full-model id on one card must not shadow a pool
target that names another integration.

Cross-integration prefix uniqueness (enforced on save) guarantees at most one
owner per prefix value; the provider order below is a deterministic tiebreak
that uniqueness makes unreachable in practice.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.config.product_capabilities import is_capability_enabled

# Deterministic tiebreak order. Lower index wins.
SIDECAR_PROVIDER_ORDER: tuple[str, ...] = (
    "claude",
    "openrouter",
    "orcarouter",
    "omniroute",
    "ollama",
    "opencode_go",
)

# Separator of an explicit pool target ``<provider>::<model>``. A pool target
# written this way names the integration it must be served by, which is how a
# full model configured on more than one integration is picked for a pool:
# ``orcarouter::z-ai/glm-5.3`` vs ``openrouter::z-ai/glm-5.3``. A target whose
# provider part names no known integration is resolved like any bare model, so
# real model ids containing ``::`` keep working.
EXPLICIT_TARGET_SEPARATOR = "::"


@dataclass(frozen=True, slots=True)
class SidecarRoutingEntry:
    """One enabled integration's routing inputs."""

    provider: str
    prefixes: tuple[SidecarPrefix, ...]
    full_models: tuple[str, ...]
    # Lower-cased full models this integration is starred as the primary route
    # for. Empty for every entry built without star information.
    starred_full_models: frozenset[str] = frozenset()


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


def parse_explicit_pool_target(target: str) -> tuple[str, str] | None:
    """Split ``<provider>::<model>`` into ``(provider, model)``.

    Returns ``None`` when ``target`` carries no ``<provider>::`` prefix, so a
    bare target - including a real model id that happens to contain ``::`` -
    stays a plain model. The provider part must be non-blank, but whether it
    names a configured integration is the caller's business.
    """

    if EXPLICIT_TARGET_SEPARATOR not in target:
        return None
    provider, _, model = target.partition(EXPLICIT_TARGET_SEPARATOR)
    normalized_provider = provider.strip().lower()
    normalized_model = model.strip()
    if not normalized_provider or not normalized_model:
        return None
    return normalized_provider, normalized_model


def _resolve_full_or_prefix(model: str, entry: SidecarRoutingEntry) -> SidecarRoutingDecision | None:
    """Resolve ``model`` against one integration: full models first, then prefixes.

    The bare-model passes of :func:`resolve_sidecar_route` restricted to a
    single entry, so an explicit pool target can never be served by another
    integration that happens to list the same model.
    """

    lowered = model.lower()
    if any(lowered == full.strip().lower() for full in entry.full_models):
        return SidecarRoutingDecision(provider=entry.provider, wire_model=model)
    best_prefix: SidecarPrefix | None = None
    best_variant = ""
    for prefix in entry.prefixes:
        for variant in prefix_variants(prefix.prefix):
            # Longest variant wins; the first of equal length is kept, the same
            # rule the cross-entry pass applies to one entry.
            if not lowered.startswith(variant) or len(variant) <= len(best_variant):
                continue
            best_prefix = prefix
            best_variant = variant
    if best_prefix is None:
        return None
    wire_model = model
    if best_prefix.strip:
        wire_model = model[len(best_variant) :].strip() or model
    return SidecarRoutingDecision(provider=entry.provider, wire_model=wire_model)


def parse_full_model_stars(raw: str | None) -> dict[str, str]:
    """Parse stored ``{full model: provider key}`` star-map JSON.

    Keys are lower-cased full models, values the provider key of the starred
    integration. Malformed or blank entries are dropped, never rejected: the
    star map is advisory routing state.
    """

    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        str(key).strip().lower(): str(value).strip()
        for key, value in parsed.items()
        if str(key).strip() and str(value).strip()
    }


def apply_full_model_stars(
    entries: tuple[SidecarRoutingEntry, ...],
    stars: Mapping[str, str],
) -> tuple[SidecarRoutingEntry, ...]:
    """Mark on each entry the full models it is starred as the primary route for.

    ``stars`` maps a lower-cased full model to the provider key of the
    integration that is the model's default route. Only entries the star
    actually names change; the rest pass through untouched.
    """

    by_provider: dict[str, set[str]] = {}
    for model, provider in stars.items():
        normalized_model = model.strip().lower()
        if not normalized_model:
            continue
        by_provider.setdefault(provider, set()).add(normalized_model)
    decorated: list[SidecarRoutingEntry] = []
    for entry in entries:
        starred = by_provider.get(entry.provider)
        if not starred:
            decorated.append(entry)
            continue
        relevant = frozenset(
            model for model in starred if any(model == full.strip().lower() for full in entry.full_models)
        )
        if not relevant:
            decorated.append(entry)
            continue
        decorated.append(replace(entry, starred_full_models=relevant))
    return tuple(decorated)


def resolve_sidecar_pool_target(
    target: str,
    entries: tuple[SidecarRoutingEntry, ...],
) -> SidecarRoutingDecision | None:
    """Resolve an alias-pool target, which names its integration explicitly.

    Unlike a bare request, a target carrying ``<provider>::`` never lets the
    full-model pass shadow it: another integration literally listing
    ``<provider>::<model>`` cannot claim a target that names its integration.
    A target without the separator, or one whose provider part names no known
    integration, resolves like any bare model via :func:`resolve_sidecar_route`.
    """

    entries = tuple(entry for entry in entries if is_capability_enabled(entry.provider))
    normalized = target.strip()
    if not normalized:
        return None
    explicit = parse_explicit_pool_target(normalized)
    if explicit is not None:
        provider_key, model_part = explicit
        for entry in entries:
            if entry.provider.lower() == provider_key:
                return _resolve_full_or_prefix(model_part, entry)
        if provider_key in SIDECAR_PROVIDER_ORDER:
            return None
    return resolve_sidecar_route(normalized, entries)


def resolve_sidecar_route(
    model: str,
    entries: tuple[SidecarRoutingEntry, ...],
) -> SidecarRoutingDecision | None:
    """Resolve the owning integration and wire model for ``model``.

    ``entries`` must contain only enabled integrations.

    Entries whose provider maps to a product capability that is disabled are
    dropped here as well, so a stale or hand-built entry can never win a route
    even if a caller forgets the capability check.
    """

    entries = tuple(entry for entry in entries if is_capability_enabled(entry.provider))
    normalized = model.strip()
    if not normalized:
        return None
    lowered = normalized.lower()

    # Pass 1: full model name exact match (case-insensitive), forwarded as-is.
    # The starred integration wins. When several enabled integrations list the
    # model and none is starred, the bare id is ambiguous: it stays unrouted
    # by default instead of silently redirecting by provider rank, and alias
    # pools must target it via ``<provider>::<model>``. A model listed by only
    # one enabled integration keeps routing even starless - the compatibility
    # policy for starless rows (legacy data or a decayed star), matching
    # pre-stars behavior where a full model routed to its only card.
    # This pass also runs before explicit-target parsing, so a configured
    # full-model id that itself contains ``::`` still resolves exactly here.
    starred_match: SidecarRoutingEntry | None = None
    full_matches: list[SidecarRoutingEntry] = []
    for entry in entries:
        if any(lowered == full.strip().lower() for full in entry.full_models):
            full_matches.append(entry)
            if starred_match is None and lowered in entry.starred_full_models:
                starred_match = entry
    if full_matches:
        if starred_match is not None:
            return SidecarRoutingDecision(provider=starred_match.provider, wire_model=normalized)
        if len(full_matches) > 1:
            return None
        return SidecarRoutingDecision(provider=full_matches[0].provider, wire_model=normalized)

    # An explicit ``<provider>::<model>`` id resolves only within the
    # integration it names. When that integration is enabled the id can
    # never be served by another one; when the provider is a known integration
    # that is not enabled the id stays unroutable instead of falling
    # through to bare-model matching, where a prefix or duplicate id on another
    # integration could claim the literal id. Only a ``::`` id whose
    # leading segment names no known provider falls through, so real model ids
    # containing ``::`` keep working.
    #
    # This pass is subordinate to the exact full-model match above, which is
    # the bare-request rule. Alias pools resolve their stored targets through
    # :func:`resolve_sidecar_pool_target`, which applies this pass first so a
    # literal full model on another card cannot shadow an explicit target.
    explicit = parse_explicit_pool_target(normalized)
    if explicit is not None:
        provider_key, model_part = explicit
        for entry in entries:
            if entry.provider.lower() == provider_key:
                return _resolve_full_or_prefix(model_part, entry)
        if provider_key in SIDECAR_PROVIDER_ORDER:
            return None

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
