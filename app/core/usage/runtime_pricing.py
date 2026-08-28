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
for callers that cannot name a provider; see :meth:`RuntimePricingRegistry.update_models`
for how ownership of a shared id is assigned and released there.

Every price served by this overlay is backed by a live listing: an id a provider
stops publishing is evicted rather than kept at its last known value. The one
case this cannot cover is a provider that stops refreshing altogether (a
disabled integration never calls ``list_models`` again), so its already-recorded
prices stay until the process restarts.

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
        """Record runtime pricing for the given ``(model_id, pricing)`` pairs.

        ``provider`` names the integration whose ``/models`` listing supplied the
        prices. They are recorded in that provider's own key space so a second
        provider listing the same id cannot redefine them. Entries with ``None``
        pricing carry no runtime price and count as unpublished by that provider.

        A named ``provider`` call is treated as an authoritative complete
        listing: the callers (:meth:`OpenRouterSidecarClient.list_models` and
        :meth:`OrcaRouterSidecarClient.list_models`) only reach this method after
        a whole ``/models`` response parsed successfully, and they raise instead
        of calling it on transport or protocol failure, so a failed refresh can
        never be mistaken for an empty catalogue. A refresh that authoritatively
        prices nothing is still a complete listing and releases everything that
        provider had claimed.

        Without a ``provider`` the pairs are merged into the unqualified overlay
        only; a partial update carries no listing authority, so nothing is
        evicted.
        """
        updates = {model_id.strip().lower(): price for model_id, price in models if model_id and price is not None}
        provider_key = _normalize_key(provider)
        if not provider_key:
            if not updates:
                return
            with self._lock:
                self._pricing.update(updates)
                for model_id in updates:
                    self._pricing_owner.pop(model_id, None)
            return
        with self._lock:
            # A ``/models`` response is a complete listing, so it replaces this
            # provider's key space rather than merging into it. Merging let a
            # provider appear to still publish an id it had dropped, which kept
            # ownership below alive forever. This runs before any early exit so
            # a listing that prices nothing still releases the provider's claims.
            self._pricing_by_provider[provider_key] = dict(updates)
            # The unqualified overlay is a compatibility fallback for callers
            # that cannot name a provider (OmniRoute and Ollama dispatch).
            # The first provider to publish an id owns the entry and keeps it
            # current across its later refreshes; a second provider listing
            # the same id cannot redefine it while the owner still publishes
            # it. Letting whichever refresh ran last win made those callers
            # persist another provider's list price as ``reference_cost_usd``.
            for model_id, price in updates.items():
                owner = self._pricing_owner.get(model_id)
                if owner is not None and owner != provider_key and model_id in self._pricing_by_provider.get(owner, {}):
                    continue
                self._pricing[model_id] = price
                self._pricing_owner[model_id] = provider_key
            self._evict_delisted(provider_key, updates)

    def _evict_delisted(self, provider_key: str, listed: Mapping[str, ModelPrice]) -> None:
        """Drop overlay entries ``provider_key`` owns but no longer publishes.

        Releasing ownership alone left the dead value in place whenever no other
        provider republished the id, so the provider-less callers kept persisting
        a price no live listing backed. An id another provider still publishes is
        handed to that provider instead of being dropped. Caller holds the lock.
        """
        stale = [
            model_id
            for model_id, owner in self._pricing_owner.items()
            if owner == provider_key and model_id not in listed
        ]
        for model_id in stale:
            successor = self._live_publisher(model_id, exclude=provider_key)
            if successor is None:
                self._pricing.pop(model_id, None)
                self._pricing_owner.pop(model_id, None)
                continue
            new_owner, price = successor
            self._pricing[model_id] = price
            self._pricing_owner[model_id] = new_owner

    def _live_publisher(self, model_id: str, *, exclude: str) -> tuple[str, ModelPrice] | None:
        """First provider other than ``exclude`` whose current listing has ``model_id``."""
        for candidate, prices in self._pricing_by_provider.items():
            if candidate == exclude:
                continue
            price = prices.get(model_id)
            if price is not None:
                return candidate, price
        return None

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
