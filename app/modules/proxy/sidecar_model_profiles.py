from __future__ import annotations

import re
from typing import cast

from app.core.clients.claude_sidecar import ClaudeSidecarConfig
from app.core.types import JsonValue
from app.core.usage.pricing import DEFAULT_MODEL_ALIASES
from app.core.usage.pricing import resolve_model_alias as resolve_pricing_model_alias
from app.modules.proxy.sidecar_routing import prefix_variants

_CLAUDE_MODEL_FAMILY_PREFIX = "claude-"
_DATE_SUFFIX_PATTERN = re.compile(r"-\d{8}$")
_REASONING_EFFORT_TOKENS: frozenset[str] = frozenset(
    {"none", "auto", "minimal", "low", "medium", "high", "xhigh", "extra", "max"}
)
_MODEL_SUFFIX_REASONING_PATTERN = re.compile(
    r"^(?P<base>.+?)(?:-(?P<effort>none|auto|minimal|low|medium|high|xhigh|extra|max))(?:-(?:thinking|reasoning))?$",
    re.IGNORECASE,
)


def canonical_sidecar_model(model: str | None) -> str | None:
    if model is None:
        return None
    normalized = model.strip()
    if not normalized:
        return None
    pricing_alias = resolve_pricing_model_alias(normalized, DEFAULT_MODEL_ALIASES)
    if pricing_alias is not None:
        return pricing_alias
    if not normalized.startswith(_CLAUDE_MODEL_FAMILY_PREFIX):
        candidate = f"{_CLAUDE_MODEL_FAMILY_PREFIX}{normalized}"
        pricing_alias = resolve_pricing_model_alias(candidate, DEFAULT_MODEL_ALIASES)
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
    wire_model, suffix_effort = _resolve_sidecar_wire_model_and_effort(stripped_model.strip())
    body["model"] = wire_model
    if suffix_effort is not None:
        _set_reasoning_effort(body, suffix_effort)
    return wire_model


def _resolve_sidecar_wire_model_and_effort(model: str) -> tuple[str, str | None]:
    if not model:
        return model, None

    pricing_alias = resolve_pricing_model_alias(model, DEFAULT_MODEL_ALIASES)
    if pricing_alias is not None and pricing_alias.lower() != model.lower():
        if not _is_date_suffix_variant(model, pricing_alias):
            effort = _extract_reasoning_effort_suffix(model, pricing_alias)
            return pricing_alias, effort

    base_model, suffix_effort = _split_model_reasoning_suffix(model)
    if not base_model.startswith(_CLAUDE_MODEL_FAMILY_PREFIX):
        candidate = f"{_CLAUDE_MODEL_FAMILY_PREFIX}{base_model}"
        if _is_known_claude_model_id(candidate):
            return candidate, suffix_effort
    return base_model, suffix_effort


def is_known_claude_sidecar_model(model: str | None) -> bool:
    if model is None:
        return False
    normalized = model.strip()
    if not normalized:
        return False
    alias = resolve_pricing_model_alias(normalized, DEFAULT_MODEL_ALIASES)
    if alias is not None and alias.startswith(_CLAUDE_MODEL_FAMILY_PREFIX):
        return True
    canonical = canonical_sidecar_model(normalized)
    if canonical is None or not canonical.startswith(_CLAUDE_MODEL_FAMILY_PREFIX):
        return False
    return resolve_pricing_model_alias(canonical, DEFAULT_MODEL_ALIASES) is not None


def _is_known_claude_model_id(model_id: str) -> bool:
    return is_known_claude_sidecar_model(model_id)


def _is_date_suffix_variant(model: str, canonical: str) -> bool:
    normalized = model.strip().lower()
    canonical_normalized = canonical.strip().lower()
    return normalized.startswith(f"{canonical_normalized}-") and _DATE_SUFFIX_PATTERN.search(normalized) is not None


def _extract_reasoning_effort_suffix(model: str, canonical: str) -> str | None:
    normalized = model.strip().lower()
    canonical_normalized = canonical.strip().lower()
    if not normalized.startswith(canonical_normalized):
        return None
    suffix = normalized[len(canonical_normalized) :].strip("-")
    if not suffix:
        return None
    tokens = [token for token in suffix.split("-") if token]
    for token in reversed(tokens):
        effort = token
        if effort == "extra":
            effort = "xhigh"
        if effort in _REASONING_EFFORT_TOKENS and effort not in {"thinking", "reasoning"}:
            return effort
    return None


def _split_model_reasoning_suffix(model: str) -> tuple[str, str | None]:
    match = _MODEL_SUFFIX_REASONING_PATTERN.match(model.strip())
    if match is None:
        return model, None
    effort = match.group("effort")
    if effort is None:
        return model, None
    normalized_effort = effort.lower()
    if normalized_effort == "extra":
        normalized_effort = "xhigh"
    if normalized_effort not in _REASONING_EFFORT_TOKENS:
        return model, None
    base = match.group("base").rstrip("-")
    if not base:
        return model, None
    return base, normalized_effort


def _set_reasoning_effort(body: dict[str, JsonValue], effort: str) -> None:
    existing = body.get("reasoning_effort")
    if isinstance(existing, str) and existing.strip():
        return
    reasoning = body.get("reasoning")
    if isinstance(reasoning, dict):
        reasoning_dict = cast(dict[str, JsonValue], reasoning)
        existing_effort = reasoning_dict.get("effort")
        if isinstance(existing_effort, str) and existing_effort.strip():
            return
    body["reasoning_effort"] = effort
