"""Runtime model pricing registry for reference-cost (savings) calculations.

This module maintains an in-memory overlay of model pricing discovered at
runtime (currently from the OpenRouter sidecar ``/models`` response) on top of
the static :data:`DEFAULT_PRICING_MODELS` table. It is used **only** for
reference-cost lookups -- i.e. "what would this request have cost on the
paid-equivalent model" -- and never changes how actual ``cost_usd`` is computed.

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

    def update_models(self, models: Iterable[tuple[str, ModelPrice | None]]) -> None:
        """Merge runtime pricing for the given ``(model_id, pricing)`` pairs.

        Entries with ``None`` pricing are ignored (no runtime price known).
        """
        updates = {model_id.strip().lower(): price for model_id, price in models if model_id and price is not None}
        if not updates:
            return
        with self._lock:
            self._pricing.update(updates)

    def runtime_pricing_for_model(self, model: str) -> ModelPrice | None:
        if not model:
            return None
        with self._lock:
            return self._pricing.get(model.strip().lower())

    def clear(self) -> None:
        with self._lock:
            self._pricing.clear()

    def snapshot(self) -> Mapping[str, ModelPrice]:
        with self._lock:
            return dict(self._pricing)


_REGISTRY = RuntimePricingRegistry()


def get_runtime_pricing_registry() -> RuntimePricingRegistry:
    return _REGISTRY


def _reference_pricing_direct(model: str) -> ModelPrice | None:
    """Reference pricing for ``model`` without free->paid resolution.

    Runtime (OpenRouter) pricing wins over the static built-in table.
    """
    runtime = _REGISTRY.runtime_pricing_for_model(model)
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


def get_reference_pricing_for_model(model: str | None) -> ModelPrice | None:
    """Resolve the paid-equivalent reference pricing for ``model``.

    For free models, the paid variant is resolved by stripping the free marker.
    Returns ``None`` when no reference price can be resolved (the caller must
    then leave ``reference_cost_usd`` unset).
    """
    if not model:
        return None

    if is_known_free_model(model):
        for candidate in _paid_equivalent_candidates(model):
            price = _reference_pricing_direct(candidate)
            if price is not None:
                return price
        return None

    return _reference_pricing_direct(model)


def calculate_reference_cost(
    model: str | None,
    usage: UsageTokens | None,
    *,
    service_tier: str | None = None,
) -> float | None:
    """Compute the paid-equivalent reference cost for a request.

    Returns ``None`` when no reference price resolves or usage is missing, so
    the caller leaves ``reference_cost_usd`` unset.
    """
    if usage is None:
        return None
    price = get_reference_pricing_for_model(model)
    if price is None:
        return None
    return calculate_cost_from_usage(usage, price, service_tier=service_tier)
