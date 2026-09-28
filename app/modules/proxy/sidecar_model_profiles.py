from __future__ import annotations

from app.core.clients.claude_sidecar import ClaudeSidecarConfig
from app.core.types import JsonValue
from app.core.usage.model_ids import (
    claude_model_identity,
    resolve_versioned_model_id,
    split_model_effort_suffix,
    strip_known_sidecar_prefix,
    strip_trailing_release_date,
)
from app.core.usage.pricing import DEFAULT_MODEL_ALIASES, DEFAULT_PRICING_MODELS
from app.core.usage.pricing import resolve_model_alias as resolve_pricing_model_alias
from app.modules.proxy.sidecar_routing import prefix_variants

_CLAUDE_MODEL_FAMILY_PREFIX = "claude-"


def _matching_claude_price_key(model_id: str) -> str | None:
    target = model_id.lower()
    if not target.startswith(_CLAUDE_MODEL_FAMILY_PREFIX):
        return None
    for key in DEFAULT_PRICING_MODELS:
        if key.lower() == target:
            return key
    return None


def canonical_sidecar_model(model: str | None) -> str | None:
    if model is None:
        return None
    normalized = model.strip()
    if not normalized:
        return None
    identity = claude_model_identity(normalized)
    priced = _matching_claude_price_key(identity)
    if priced is not None:
        return priced
    if identity.lower().startswith(_CLAUDE_MODEL_FAMILY_PREFIX):
        return identity
    restored = _matching_claude_price_key(f"{_CLAUDE_MODEL_FAMILY_PREFIX}{identity}")
    if restored is not None:
        return restored
    pricing_alias = resolve_versioned_model_id(normalized) or resolve_pricing_model_alias(
        normalized, DEFAULT_MODEL_ALIASES
    )
    if pricing_alias is not None:
        return pricing_alias
    return normalized


def sidecar_prefixed_model_ids(model_id: str, config: ClaudeSidecarConfig) -> tuple[str, ...]:
    ids: list[str] = [model_id]
    seen = {model_id}
    for prefix in config.prefixes:
        # Only strip-enabled prefixes produce alias-prefixed catalog IDs; a
        # non-stripping prefix forwards the model as-is, so advertising
        # ``<prefix><model_id>`` would not round-trip to ``model_id``.
        if not prefix.strip:
            continue
        for variant in prefix_variants(prefix.prefix):
            alias_id = f"{variant}{model_id}"
            if alias_id not in seen:
                seen.add(alias_id)
                ids.append(alias_id)
    return tuple(ids)


def apply_sidecar_model_profile(body: dict[str, JsonValue], *, stripped_model: str) -> str:
    wire_model, _ = apply_sidecar_model_profile_with_suffix_effort(body, stripped_model=stripped_model)
    return wire_model


def apply_sidecar_model_profile_with_suffix_effort(
    body: dict[str, JsonValue], *, stripped_model: str
) -> tuple[str, bool]:
    """Apply the canonical-model + suffix-effort profile.

    Returns the resolved wire model and whether a model-name suffix effort was
    applied. The boolean lets callers keep an explicit suffix as the highest
    precedence (it must beat a configured override).
    """

    wire_model, suffix_effort = _resolve_sidecar_wire_model_and_effort(stripped_model.strip())
    body["model"] = wire_model
    if suffix_effort is not None:
        _set_reasoning_effort(body, suffix_effort)
    return wire_model, suffix_effort is not None


def _resolve_sidecar_wire_model_and_effort(model: str) -> tuple[str, str | None]:
    if not model:
        return model, None
    stripped = strip_known_sidecar_prefix(model.strip())
    if not stripped:
        return model, None

    versioned = resolve_versioned_model_id(stripped)
    base, effort = split_model_effort_suffix(stripped)
    if versioned is not None and versioned.lower().startswith(_CLAUDE_MODEL_FAMILY_PREFIX):
        undated = strip_trailing_release_date(base)
        if undated.lower() == versioned.lower() and base.lower() != versioned.lower():
            return base, effort
        return versioned, effort

    undated = strip_trailing_release_date(base)
    if undated.lower() != base.lower():
        return base, effort
    if not undated.lower().startswith(_CLAUDE_MODEL_FAMILY_PREFIX):
        restored = _matching_claude_price_key(f"{_CLAUDE_MODEL_FAMILY_PREFIX}{undated}")
        if restored is not None:
            return restored, effort
    priced = _matching_claude_price_key(undated)
    if priced is not None:
        return priced, effort
    return undated, effort


def is_known_claude_sidecar_model(model: str | None) -> bool:
    if model is None:
        return False
    normalized = model.strip()
    if not normalized:
        return False
    canonical = canonical_sidecar_model(normalized)
    if canonical is None:
        return False
    return _matching_claude_price_key(canonical) is not None


def _set_reasoning_effort(body: dict[str, JsonValue], effort: str) -> None:
    existing = body.get("reasoning_effort")
    if isinstance(existing, str) and existing.strip():
        return
    reasoning = body.get("reasoning")
    if isinstance(reasoning, dict):
        reasoning_dict = reasoning
        existing_effort = reasoning_dict.get("effort")
        if isinstance(existing_effort, str) and existing_effort.strip():
            return
    body["reasoning_effort"] = effort


def set_reasoning_effort_override(body: dict[str, JsonValue], effort: str | None) -> None:
    """Force the configured ``reasoning_effort`` onto the forwarded payload.

    Unlike a fill-when-absent default, this overrides any client-supplied
    top-level ``reasoning_effort`` and any nested ``reasoning.effort``: the
    configured value is written to the top level and the nested effort is
    stripped so a downstream promotion of ``reasoning.effort`` cannot win. A
    blank/None ``effort`` is a no-op (override unset).
    """

    if effort is None:
        return
    normalized = effort.strip()
    if not normalized:
        return
    reasoning = body.get("reasoning")
    if isinstance(reasoning, dict):
        reasoning_dict = reasoning
        reasoning_dict.pop("effort", None)
        if not reasoning_dict:
            body.pop("reasoning", None)
    body["reasoning_effort"] = normalized


def read_reasoning_effort(body: dict[str, JsonValue]) -> str | None:
    """Return the reasoning effort present on a chat payload body, or ``None``.

    Reads top-level ``reasoning_effort`` first, then a nested ``reasoning.effort``.
    Used to capture the client-requested effort before any override is applied.
    """

    top_level = body.get("reasoning_effort")
    if isinstance(top_level, str) and top_level.strip():
        return top_level.strip()
    reasoning = body.get("reasoning")
    if isinstance(reasoning, dict):
        effort = reasoning.get("effort")
        if isinstance(effort, str) and effort.strip():
            return effort.strip()
    return None
