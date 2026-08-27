"""Runtime model pricing registry for reference-cost (savings) calculations.

This module maintains an in-memory overlay of model pricing discovered at
runtime (from a sidecar ``/models`` response) on top of the static
:data:`DEFAULT_PRICING_MODELS` table. It is used **only** for reference-cost
lookups -- i.e. "what would this request have cost on the paid-equivalent
model" -- and never changes how actual ``cost_usd`` is computed.

Providers publish overlapping model ids (``deepseek/deepseek-chat`` is listed by
both OpenRouter and OrcaRouter) at different list prices, so entries are also
qualified by the provider that discovered them and a lookup resolves against the
provider that served the request. The unqualified overlay stays as the fallback
for callers that do not know a provider and for ids only one provider lists.

A request served by a free model (``...:free``) records ``cost_usd = 0`` but a
positive reference cost resolved from the paid variant, so dashboards can show
how much was saved.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable, Mapping

from app.core.usage.pricing import (
    DEFAULT_PRICING_MODELS,
    ModelPrice,
    UsageTokens,
    calculate_cost_from_usage,
    get_pricing_for_model,
    is_known_free_model,
)

# Markers that denote a free model variant, e.g. ``vendor/model:free``,
# ``vendor/model-free``, ``vendor/model_free``.
_FREE_MARKER_RE = re.compile(r"[:_-]free\b", re.IGNORECASE)


class RuntimePricingRegistry:
    """Thread-safe in-memory overlay of runtime-discovered model pricing."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pricing: dict[str, ModelPrice] = {}
        self._pricing_by_provider: dict[str, dict[str, ModelPrice]] = {}
        self._pricing_owner: dict[str, str] = {}

    def update_models(
        self,
        models: Iterable[tuple[str, ModelPrice | None]],
        *,
        provider: str | None = None,
    ) -> None:
        """Merge runtime pricing for the given ``(model_id, pricing)`` pairs.

        ``provider`` names the integration whose ``/models`` listing supplied the
        prices. They are recorded in that provider's own key space so a second
        provider listing the same id cannot redefine them. Entries with ``None``
        pricing are ignored (no runtime price known).
        """
        updates = {model_id.strip().lower(): price for model_id, price in models if model_id and price is not None}
        if not updates:
            return
        provider_key = _normalize_key(provider)
        with self._lock:
            if provider_key:
                self._pricing_by_provider.setdefault(provider_key, {}).update(updates)
                # The unqualified overlay is a compatibility fallback for callers
                # that cannot name a provider (OmniRoute and Ollama dispatch).
                # The first provider to publish an id owns the entry and keeps it
                # current across its later refreshes; a second provider listing
                # the same id cannot redefine it. Letting whichever /models
                # refresh ran last win made those callers persist another
                # provider's list price as ``reference_cost_usd``.
                for model_id, price in updates.items():
                    owner = self._pricing_owner.get(model_id)
                    if owner is not None and owner != provider_key:
                        continue
                    self._pricing[model_id] = price
                    self._pricing_owner[model_id] = provider_key
            else:
                self._pricing.update(updates)
                for model_id in updates:
                    self._pricing_owner.pop(model_id, None)

    def runtime_pricing_for_model(self, model: str, *, provider: str | None = None) -> ModelPrice | None:
        if not model:
            return None
        model_key = _normalize_key(model)
        provider_key = _normalize_key(provider)
        with self._lock:
            if provider_key:
                own_price = self._pricing_by_provider.get(provider_key, {}).get(model_key)
                if own_price is not None:
                    return own_price
            return self._pricing.get(model_key)

    def clear(self) -> None:
        with self._lock:
            self._pricing.clear()
            self._pricing_by_provider.clear()
            self._pricing_owner.clear()

    def snapshot(self) -> Mapping[str, ModelPrice]:
        with self._lock:
            return dict(self._pricing)


def _normalize_key(value: str | None) -> str:
    return (value or "").strip().lower()


_REGISTRY = RuntimePricingRegistry()


def get_runtime_pricing_registry() -> RuntimePricingRegistry:
    return _REGISTRY


def _reference_pricing_direct(model: str, provider: str | None = None) -> ModelPrice | None:
    """Reference pricing for ``model`` without free->paid resolution.

    The serving provider's own runtime price wins over another provider's
    listing of the same id, which in turn wins over the static built-in table.
    """
    runtime = _REGISTRY.runtime_pricing_for_model(model, provider=provider)
    if runtime is not None:
        return runtime
    resolved = get_pricing_for_model(model, DEFAULT_PRICING_MODELS, None)
    if resolved is None:
        return None
    return resolved[1]


def _paid_equivalent_candidates(model: str) -> list[str]:
    """Candidate paid-equivalent model ids for a free model name."""
    candidates: list[str] = []
    stripped = _FREE_MARKER_RE.sub("", model).strip()
    if stripped and stripped != model:
        candidates.append(stripped)
    return candidates


def get_reference_pricing_for_model(model: str | None, *, provider: str | None = None) -> ModelPrice | None:
    """Resolve the paid-equivalent reference pricing for ``model``.

    For free models, the paid variant is resolved by stripping the free marker.
    Returns ``None`` when no reference price can be resolved (the caller must
    then leave ``reference_cost_usd`` unset).
    """
    if not model:
        return None

    if is_known_free_model(model):
        for candidate in _paid_equivalent_candidates(model):
            price = _reference_pricing_direct(candidate, provider)
            if price is not None:
                return price
        return None

    return _reference_pricing_direct(model, provider)


def calculate_reference_cost(
    model: str | None,
    usage: UsageTokens | None,
    *,
    service_tier: str | None = None,
    provider: str | None = None,
) -> float | None:
    """Compute the paid-equivalent reference cost for a request.

    Returns ``None`` when no reference price resolves or usage is missing, so
    the caller leaves ``reference_cost_usd`` unset.
    """
    if usage is None:
        return None
    price = get_reference_pricing_for_model(model, provider=provider)
    if price is None:
        return None
    return calculate_cost_from_usage(usage, price, service_tier=service_tier)
