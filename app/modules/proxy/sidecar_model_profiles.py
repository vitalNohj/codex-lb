from __future__ import annotations

from app.core.clients.claude_sidecar import ClaudeSidecarConfig
from app.core.types import JsonValue
from app.core.usage.model_ids import resolve_versioned_model_id, strip_known_sidecar_prefix
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
    """The id after one known routing prefix, with no other renaming.

    A dotted spelling, a release date, and an effort suffix stay. Bounds and
    allowlists then exact-match that string against a known row.
    """
    if model is None:
        return None
    normalized = model.strip()
    if not normalized:
        return None
    stripped = strip_known_sidecar_prefix(normalized)
    if not stripped:
        return None
    priced = _matching_claude_price_key(stripped)
    if priced is not None:
        return priced
    if stripped.lower().startswith(_CLAUDE_MODEL_FAMILY_PREFIX):
        return stripped
    pricing_alias = resolve_versioned_model_id(stripped) or resolve_pricing_model_alias(stripped, DEFAULT_MODEL_ALIASES)
    if pricing_alias is not None:
        return pricing_alias
    return stripped


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
    """Forward the routed model id without renaming it.

    Routing already removed a configured prefix. A dotted spelling, a release
    date, and a thinking or effort suffix stay on the id. The boolean is
    always false: the model name is not an effort source, so the caller
    applies the operator override on its own.
    """

    wire_model = stripped_model.strip()
    body["model"] = wire_model
    return wire_model, False


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
