"""The model-resolution boundary shared by discovery, dispatch and settlement.

Source adapters retain their refresh/storage responsibilities. Resolution is
synchronous and never performs network or database I/O. Provider/source prices
are explicit inputs so a same-named subscription cannot price an external row.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from app.core.models.local import LocalCatalog, load_local_catalog
from app.core.models.router import get_router_models
from app.core.models.types import ModelPrice
from app.core.types import JsonValue
from app.core.usage.model_ids import resolve_versioned_model_id, strip_known_sidecar_prefix
from app.core.utils.json_guards import is_json_mapping

if TYPE_CHECKING:
    from app.core.openai.model_registry import UpstreamModel


@dataclass(frozen=True)
class ModelRecord:
    canonical_id: str
    aliases: tuple[str, ...]
    provider: str | None
    context_window: int | None
    max_context_window: int | None
    max_output_tokens: int | None
    thinking_levels: tuple[str, ...] | None
    thinking_min: int | None
    thinking_max: int | None
    input_modalities: tuple[str, ...] | None
    output_modalities: tuple[str, ...] | None
    price: ModelPrice | None
    provenance: dict[str, str]


def _positive_int(value: JsonValue | None) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _strings(value: JsonValue | None) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    return tuple(item.strip().lower() for item in value if isinstance(item, str) and item.strip())


def catalog_input_modalities(raw: Mapping[str, JsonValue] | None) -> tuple[str, ...] | None:
    """Parse a provider row once, preserving absent versus explicitly empty."""
    if raw is None:
        return None
    direct = _strings(raw.get("input_modalities"))
    if direct is not None:
        return direct
    architecture = raw.get("architecture")
    if not is_json_mapping(architecture):
        return None
    nested = _strings(architecture.get("input_modalities"))
    if nested is not None:
        return nested
    modality = architecture.get("modality")
    if not isinstance(modality, str) or "->" not in modality:
        return None
    parts = tuple(part.strip().lower() for part in modality.split("->", 1)[0].split("+") if part.strip())
    return parts or None


def resolve_model(
    model: str,
    *,
    upstream: UpstreamModel | None = None,
    provider: str | None = None,
    price: ModelPrice | None = None,
    isolated_price: bool = False,
    raw: Mapping[str, JsonValue] | None = None,
    published_context: int | None = None,
    published_output: int | None = None,
    overrides: Mapping[str, int] | None = None,
    fallback_context: int | None = None,
) -> ModelRecord:
    """Resolve a single model, preserving provider and operator boundaries.

    ``isolated_price`` means ``price`` is the serving source's authoritative
    snapshot, even when absent. Never replace an unknown external rate with a
    substring match from another provider. ``upstream`` carries the selected
    source's metadata and prevents subscription metadata leaking into that source.
    """
    from app.core.usage.pricing import get_pricing_for_model
    from app.core.usage.pricing_catalog import get_active_model_capabilities

    normalized = model.strip().lower()
    provider = provider.strip().lower() if provider is not None else None
    routed_identity = strip_known_sidecar_prefix(normalized)
    identity = resolve_versioned_model_id(routed_identity) or routed_identity
    local_models = load_local_catalog().models
    exact_alias = next((key for key, value in local_models.items() if identity in value.aliases), None)
    if identity not in local_models and exact_alias is not None:
        identity = exact_alias
    entry = local_models.get(identity)
    aliases = {alias: key for key, value in local_models.items() for alias in value.aliases}
    all_prices, price_provenance = _price_layers()
    price_identity = identity if exact_alias is not None else normalized
    resolved_price = None if isolated_price else get_pricing_for_model(price_identity, all_prices, aliases)
    # Price aliases exist for historical billing, not for capability inheritance.
    canonical = resolved_price[0] if resolved_price is not None else identity
    price = price if isolated_price else (resolved_price[1] if resolved_price is not None else price)
    provenance: dict[str, str] = {"canonical_id": "identity"}
    if canonical != identity or exact_alias is not None:
        provenance["canonical_id"] = "local:alias"
    if provider is not None:
        provenance["provider"] = "external:" + provider
    if price is not None:
        if isolated_price:
            layer = "external:" + (provider or "source")
            provenance.update({f"price.{key}": layer for key, value in asdict(price).items() if value is not None})
        else:
            provenance.update(price_provenance.get(canonical, {}))

    context = fallback_context
    maximum = None
    output = None
    thinking = None
    thinking_min = None
    thinking_max = None
    inputs = None
    outputs = None
    resolved_provider = provider
    if context is not None:
        provenance["context_window"] = "fallback"

    router = get_router_models().get(identity)
    if router is not None:
        if resolved_provider is None:
            resolved_provider = router.catalog_provider or router.owned_by
            if resolved_provider is not None:
                provenance["provider"] = "cliproxy"
        context = router.context_length or context
        output = router.max_completion_tokens
        inputs = router.input_modalities
        outputs = router.output_modalities
        if router.thinking is not None:
            thinking = router.thinking.levels
            thinking_min, thinking_max = router.thinking.min, router.thinking.max
        for key, value in {
            "context_window": router.context_length,
            "max_output_tokens": output,
            "thinking_levels": thinking,
            "thinking_min": thinking_min,
            "thinking_max": thinking_max,
            "input_modalities": inputs,
            "output_modalities": outputs,
        }.items():
            if value is not None:
                provenance[key] = "cliproxy"

    # Keep the existing models.dev capability source as additional evidence.
    capability = get_active_model_capabilities().get(identity)
    if capability is not None:
        if capability.context_window is not None:
            context = capability.context_window
            provenance["context_window"] = "external:models.dev"
        if capability.max_output_tokens is not None:
            output = capability.max_output_tokens
            provenance["max_output_tokens"] = "external:models.dev"
        if capability.input_modalities is not None:
            inputs = capability.input_modalities
            provenance["input_modalities"] = "external:models.dev"

    from app.core.openai.model_registry import get_model_registry

    registry = get_model_registry()
    snapshot = registry.get_snapshot()
    if upstream is None and not isolated_price:
        upstream = registry.get_models_for_metadata().get(identity)
    if upstream is not None:
        source = "source" if upstream.source_kind != "subscription" else "codex"
        live = source == "codex" and snapshot is not None and upstream.slug in snapshot.models
        if not live and source == "codex":
            source = "local:bootstrap"
        maximum = _positive_int(upstream.raw.get("max_context_window"))
        context = maximum if live and maximum is not None else upstream.context_window
        inputs = upstream.input_modalities
        thinking = tuple(level.effort for level in upstream.supported_reasoning_levels)
        declared_output = _positive_int(upstream.raw.get("max_output_tokens"))
        if declared_output is not None:
            output = declared_output
            provenance["max_output_tokens"] = source
        provenance.update(context_window=source, input_modalities=source, thinking_levels=source)
        if maximum is not None:
            provenance["max_context_window"] = source
        if resolved_provider is None:
            resolved_provider = "openai" if upstream.source_kind == "subscription" else "openai_compatible"
            provenance["provider"] = source

    if raw is not None:
        row_context = _positive_int(raw.get("context_length")) or _positive_int(raw.get("context_window"))
        top = raw.get("top_provider")
        if row_context is None and isinstance(top, dict):
            row_context = _positive_int(top.get("context_length"))
        if row_context is not None:
            context = row_context
            provenance["context_window"] = "external:" + (provider or "provider")
        row_output = _positive_int(raw.get("max_output_tokens")) or _positive_int(raw.get("max_completion_tokens"))
        if row_output is not None:
            output = row_output
            provenance["max_output_tokens"] = "external:" + (provider or "provider")
        row_inputs = catalog_input_modalities(raw)
        if row_inputs is not None and not (capability is not None and capability.input_modalities is not None):
            inputs = row_inputs
            provenance["input_modalities"] = "external:" + (provider or "provider")
        row_outputs = _strings(raw.get("output_modalities"))
        if row_outputs is not None:
            outputs = row_outputs
            provenance["output_modalities"] = "external:" + (provider or "provider")

    if published_context is not None:
        context = published_context
        provenance["context_window"] = "cliproxy:live"
    if published_output is not None:
        output = published_output
        provenance["max_output_tokens"] = "cliproxy:live"

    # Local capability corrections apply to exact identities only. A billing
    # alias must not invent capabilities for a different Claude release.
    capability_profile = provider or "subscription"
    local_capabilities_apply = (
        entry is not None
        and (not entry.capability_providers or capability_profile in entry.capability_providers)
        and (not entry.legacy_sidecar_bounds or capability_profile in {"subscription", "cliproxy"})
    )
    if entry is not None and local_capabilities_apply and (upstream is None or upstream.source_kind == "subscription"):
        if entry.provider is not None:
            resolved_provider = entry.provider
            provenance["provider"] = "local"
        for key in (
            "context_window",
            "max_context_window",
            "max_output_tokens",
            "thinking_levels",
            "input_modalities",
            "output_modalities",
        ):
            value = getattr(entry, key)
            if value is None:
                continue
            if (
                entry.legacy_sidecar_bounds
                and key == "input_modalities"
                and raw is not None
                and catalog_input_modalities(raw) is not None
            ):
                continue
            if entry.legacy_sidecar_bounds and (
                (key == "context_window" and published_context is not None)
                or (key == "max_output_tokens" and published_output is not None)
            ):
                continue
            if key == "context_window":
                context = value
            elif key == "max_context_window":
                maximum = value
            elif key == "max_output_tokens":
                output = value
            elif key == "thinking_levels":
                thinking = value
            elif key == "input_modalities":
                inputs = value
            elif key == "output_modalities":
                outputs = value
            provenance[key] = "local"
        if (
            entry.fallback_max_output_tokens is not None
            and published_output is None
            and (raw is None or _positive_int(raw.get("max_output_tokens")) is None)
            and (upstream is None or _positive_int(upstream.raw.get("max_output_tokens")) is None)
        ):
            output = entry.fallback_max_output_tokens
            provenance["max_output_tokens"] = "local:fallback"
        if entry.respect_upstream_ceiling and upstream is not None:
            upstream_ceiling = _positive_int(upstream.raw.get("max_context_window"))
            live = snapshot is not None and upstream.slug in snapshot.models
            if upstream_ceiling is not None and (live or upstream_ceiling > upstream.context_window):
                if maximum is None or upstream_ceiling < maximum:
                    maximum = upstream_ceiling
                    provenance["max_context_window"] = "codex" if live else "local:bootstrap"
                if context is not None and maximum is not None and context > maximum:
                    context = maximum
                    provenance["context_window"] = provenance["max_context_window"]
    if entry is not None and isolated_price and provider in entry.provider_prices:
        price = entry.provider_prices[provider]
        provenance = {key: value for key, value in provenance.items() if not key.startswith("price.")}
        provenance.update(
            {f"price.{key}": "local:" + provider for key, value in asdict(price).items() if value is not None}
        )

    if overrides is not None and model in overrides:
        override = overrides[model]
        # Preserve the operator contract: a synthetic max == base is not a
        # ceiling. An explicit live Codex/local maximum is a real ceiling.
        base = upstream.context_window if upstream is not None else context
        has_ceiling = maximum is not None and (
            provenance.get("max_context_window") in {"local", "codex"} or (base is not None and maximum > base)
        )
        context = min(override, maximum) if has_ceiling and maximum is not None else override
        provenance["context_window"] = "operator"

    return ModelRecord(
        canonical_id=canonical,
        aliases=entry.aliases if entry is not None else (),
        provider=resolved_provider,
        context_window=context,
        max_context_window=maximum,
        max_output_tokens=output,
        thinking_levels=thinking,
        thinking_min=thinking_min,
        thinking_max=thinking_max,
        input_modalities=inputs,
        output_modalities=outputs,
        price=price,
        provenance=provenance,
    )


_price_cache: tuple[dict[str, ModelPrice], LocalCatalog, dict[str, ModelPrice], dict[str, dict[str, str]]] | None = None


def _price_layers() -> tuple[dict[str, ModelPrice], dict[str, dict[str, str]]]:
    from app.core.usage.pricing_catalog import get_source_prices, merge_catalogs

    global _price_cache
    source = get_source_prices()
    local = load_local_catalog()
    if _price_cache is not None and _price_cache[0] is source and _price_cache[1] is local:
        return _price_cache[2], _price_cache[3]
    fallbacks = {
        model: entry.fallback_price for model, entry in local.models.items() if entry.fallback_price is not None
    }
    # Retain the existing compatibility rule: supplement missing fields only
    # when the complete known rate groups agree with the external record.
    prices = merge_catalogs(source, fallbacks)
    provenance = {}
    for model, price in prices.items():
        source_fields = asdict(source[model]) if model in source else {}
        provenance[model] = {
            f"price.{key}": "external:pricing" if source_fields.get(key) is not None else "local:fallback"
            for key, value in asdict(price).items()
            if value is not None
        }
    for model, entry in local.models.items():
        if entry.price is not None:
            prices[model] = entry.price
            provenance[model] = {
                f"price.{key}": "local" for key, value in asdict(entry.price).items() if value is not None
            }
        if not entry.price_overrides:
            continue
        previous = prices.get(model)
        values = asdict(previous) if previous is not None else {}
        values.update(entry.price_overrides)
        if "input_per_1m" not in values or "output_per_1m" not in values:
            raise ValueError(f"Local price for {model} needs input_per_1m and output_per_1m")
        prices[model] = ModelPrice(**values)
        provenance.setdefault(model, {}).update({f"price.{key}": "local" for key in entry.price_overrides})
    _price_cache = source, local, prices, provenance
    return prices, provenance


def catalog_prices() -> dict[str, ModelPrice]:
    return dict(_price_layers()[0])
