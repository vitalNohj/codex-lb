"""Validated, exact-id capability metadata from the public models.dev catalog."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    input_modalities: tuple[str, ...] | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None


def _positive_limit(value: JsonValue) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _input_modalities(value: JsonValue) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    modalities: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            return None
        modalities.append(item.strip().lower())
    return tuple(dict.fromkeys(modalities))


def _capabilities(modalities: JsonValue, context: JsonValue, output: JsonValue) -> ModelCapabilities:
    return ModelCapabilities(_input_modalities(modalities), _positive_limit(context), _positive_limit(output))


def parse_models_dev_capabilities(payload: JsonValue) -> dict[str, ModelCapabilities]:
    """Read Anthropic rows without pricing aliases or model-family inference."""
    if not is_json_mapping(payload):
        return {}
    provider = payload.get("anthropic")
    if not is_json_mapping(provider):
        return {}
    models = provider.get("models")
    if not is_json_mapping(models):
        return {}
    result: dict[str, ModelCapabilities] = {}
    for model, raw in models.items():
        if not model or not is_json_mapping(raw):
            continue
        modalities = raw.get("modalities")
        limits = raw.get("limit")
        entry = _capabilities(
            modalities.get("input") if is_json_mapping(modalities) else None,
            limits.get("context") if is_json_mapping(limits) else None,
            limits.get("output") if is_json_mapping(limits) else None,
        )
        if entry != ModelCapabilities():
            result[model] = entry
    return result


def decode_model_capabilities(payload: JsonValue) -> dict[str, ModelCapabilities]:
    """Legacy pricing snapshots have no capability map and decode as empty."""
    if not is_json_mapping(payload):
        return {}
    models = payload.get("model_capabilities")
    if not is_json_mapping(models):
        return {}
    return {
        model: _capabilities(raw.get("input_modalities"), raw.get("context_window"), raw.get("max_output_tokens"))
        for model, raw in models.items()
        if model and is_json_mapping(raw)
    }


def merge_model_capabilities(
    primary: dict[str, ModelCapabilities], secondary: dict[str, ModelCapabilities]
) -> dict[str, ModelCapabilities]:
    """Keep last-good fields when a partial refresh omits or corrupts them."""
    result = dict(secondary)
    for model, entry in primary.items():
        previous = secondary.get(model, ModelCapabilities())
        result[model] = ModelCapabilities(
            entry.input_modalities if entry.input_modalities is not None else previous.input_modalities,
            entry.context_window if entry.context_window is not None else previous.context_window,
            entry.max_output_tokens if entry.max_output_tokens is not None else previous.max_output_tokens,
        )
    return result
