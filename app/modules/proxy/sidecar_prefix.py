from __future__ import annotations

from app.core.clients.claude_sidecar import ClaudeSidecarConfig

_BUILTIN_SIDECAR_ALIAS_PREFIXES: tuple[str, ...] = ("cp-", "cp_")


def is_custom_alias_prefix(prefix: str) -> bool:
    return prefix.endswith(("-", "_"))


def sidecar_prefix_variants(prefix: str) -> tuple[str, ...]:
    normalized = prefix.strip().lower()
    if not normalized:
        return ()
    if normalized.endswith("-"):
        return (normalized, f"{normalized[:-1]}_")
    if normalized.endswith("_"):
        return (normalized, f"{normalized[:-1]}-")
    return (normalized,)


def matching_sidecar_prefix(model: str, config: ClaudeSidecarConfig) -> str | None:
    normalized = model.strip().lower()
    best: str | None = None
    for prefix in config.model_prefixes:
        for candidate in sidecar_prefix_variants(prefix):
            if normalized.startswith(candidate) and (best is None or len(candidate) > len(best)):
                best = candidate
    for candidate in _BUILTIN_SIDECAR_ALIAS_PREFIXES:
        if normalized.startswith(candidate) and (best is None or len(candidate) > len(best)):
            best = candidate
    return best


def strip_sidecar_model_prefix(model: str, config: ClaudeSidecarConfig) -> str:
    normalized_model = model.strip()
    prefix = matching_sidecar_prefix(normalized_model, config)
    if prefix is None or not is_custom_alias_prefix(prefix):
        return normalized_model
    return normalized_model[len(prefix) :].strip() or normalized_model
