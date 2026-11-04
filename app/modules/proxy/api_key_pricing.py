"""Whether a request's model has a real price on the route that will serve it.

A shared API key refuses a model that is not priced yet (see
``ApiKeysService.enforce_limits_for_request``). Only the dispatch path knows
which price table settles a request, so each one hands admission the check that
matches its own settlement:

* Codex, Ollama, OmniRoute, images, and transcription settle from the static
  price table, which is admission's default.
* Sidecars that take part in external price resolution settle from the
  persisted external price store, under their pricing provider.
* Model sources settle from the source's own per-model rates.
* Requests that never charge a cost (model listings, file uploads) are always
  allowed. A shared key's model listing instead leaves out every model that
  ``priced_listed_models`` says it would be refused.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.core.usage.external_pricing import (
    is_external_priced_provider,
    known_price_snapshot,
    model_has_billable_price,
)
from app.core.usage.external_pricing.providers import PROVIDER_CLIPROXY
from app.core.usage.pricing import get_pricing_for_model, model_price_is_billable
from app.db.models import ModelSource
from app.modules.api_keys.service import ModelPricedCheck, static_model_is_priced
from app.modules.model_sources.catalog import source_model_has_price, source_model_price
from app.modules.proxy.model_aliasing import resolve_model_alias_pool
from app.modules.proxy.model_pricing import ModelPricing, model_pricing
from app.modules.proxy.sidecar_routing import SidecarRoutingEntry, resolve_sidecar_pool_target, resolve_sidecar_route
from app.modules.settings.model_alias_pools import ModelAliasPool

logger = logging.getLogger(__name__)

# Sidecar routes whose pricing provider is not named like the route. ``claude``
# is CLIProxyAPI, which prices everything it relays under ``cliproxy``.
_ROUTE_PRICING_PROVIDERS: dict[str, str] = {"claude": PROVIDER_CLIPROXY}


async def route_model_is_priced(provider: str, model: str) -> bool:
    """Whether settlement on sidecar route ``provider`` charges ``model`` a real, nonzero rate."""
    pricing_provider = _ROUTE_PRICING_PROVIDERS.get(provider, provider)
    if not is_external_priced_provider(pricing_provider):
        # Ollama and OmniRoute take no part in external pricing; their
        # settlement prices the model from the static table.
        return static_model_is_priced(model)
    return await model_has_billable_price(provider=pricing_provider, model=model)


def route_price_check(provider: str, model: str) -> ModelPricedCheck:
    """The admission price check for a request served by sidecar route ``provider``."""

    async def check() -> bool:
        return await route_model_is_priced(provider, model)

    return check


def pool_price_check(routes: Sequence[tuple[str, str]]) -> ModelPricedCheck:
    """The admission price check for an alias pool, as ``(provider, model)`` routes.

    Failover can land on any of the pool's targets, so every one must be priced.
    """

    async def check() -> bool:
        for provider, model in routes:
            if not await route_model_is_priced(provider, model):
                return False
        return True

    return check


def source_price_check(source: ModelSource, model: str, *, transcription: bool = False) -> ModelPricedCheck:
    """The admission price check for a request served by a model source.

    Only a transcription settles from the source's per-minute audio rate; every
    other source endpoint needs a token rate.
    """

    async def check() -> bool:
        return source_model_has_price(source, model, accepts_audio_rate=transcription)

    return check


async def never_charged() -> bool:
    """The admission price check for a request that never charges a cost."""
    return True


@dataclass(frozen=True, slots=True)
class _ListedTarget:
    """One model a listed id can land on, and how it would be priced."""

    model: str
    pricing_provider: str | None
    source: ModelSource | None


def _listed_targets(
    model: str,
    *,
    routing_entries: tuple[SidecarRoutingEntry, ...],
    sources_by_model: Mapping[str, ModelSource],
    aliases: Mapping[str, ModelAliasPool],
) -> tuple[_ListedTarget, ...]:
    """Every model a request for ``model`` can be served as, each with its price table.

    Mirrors dispatch: the name resolves through the alias map first, and an
    alias target takes the pool-target routing rule (the one chat dispatch
    applies to every alias), a bare name the exact-match rule. A target a
    sidecar owns is priced under that sidecar's pricing provider, else by the
    model source listing it, else by the static table.
    """

    resolved = resolve_model_alias_pool(model, aliases)
    aliased = resolved is not None and resolved.alias is not None
    targets = resolved.targets if resolved is not None else (model,)
    listed: list[_ListedTarget] = []
    for target in targets:
        decision = (
            resolve_sidecar_pool_target(target, routing_entries)
            if aliased
            else resolve_sidecar_route(target, routing_entries)
        )
        if decision is not None:
            listed.append(
                _ListedTarget(
                    model=target,
                    pricing_provider=_ROUTE_PRICING_PROVIDERS.get(decision.provider, decision.provider),
                    source=None,
                )
            )
        else:
            listed.append(_ListedTarget(model=target, pricing_provider=None, source=sources_by_model.get(target)))
    return tuple(listed)


@dataclass(frozen=True)
class ListedModelPrices:
    billable: frozenset[str]
    pricing: Mapping[str, ModelPricing]


async def listed_model_prices(
    models: Sequence[str],
    *,
    routing_entries: tuple[SidecarRoutingEntry, ...],
    sources_by_model: Mapping[str, ModelSource],
    aliases: Mapping[str, ModelAliasPool],
) -> ListedModelPrices:
    """Prices and shared-key admission for a catalog, using one external read.

    Each target uses its request settlement's price table. An alias can expose
    one price only when all targets have identical effective rates. A differing
    pool can still be billable for shared keys, but has no single listed price.
    """

    try:
        targets_by_model = {
            model: _listed_targets(
                model,
                routing_entries=routing_entries,
                sources_by_model=sources_by_model,
                aliases=aliases,
            )
            for model in dict.fromkeys(models)
        }
        external_keys = {
            (target.pricing_provider, target.model)
            for targets in targets_by_model.values()
            for target in targets
            if target.pricing_provider is not None and is_external_priced_provider(target.pricing_provider)
        }
        # ``None`` when the store cannot be read: every external target is unpriced.
        # The same read schedules a lookup for every external id with no stored
        # rate. This list still answers from the rows that exist now; the next
        # list publishes a rate once that lookup resolves one.
        external_prices = await known_price_snapshot(external_keys, schedule_unpriced=True)
    except Exception:
        logger.warning("shared_api_key_listing_price_check_failed count=%d", len(models), exc_info=True)
        return ListedModelPrices(billable=frozenset(), pricing={})

    def target_price(target: _ListedTarget) -> tuple[ModelPricing | None, bool]:
        source_rates = target.pricing_provider is None and target.source is not None
        if target.pricing_provider is not None and is_external_priced_provider(target.pricing_provider):
            price = external_prices(target.pricing_provider, target.model) if external_prices is not None else None
        elif target.pricing_provider is None and target.source is not None:
            price = source_model_price(target.source, target.model)
        else:
            # Ollama and OmniRoute settle from the static table, as does every
            # model no sidecar or source owns.
            resolved = get_pricing_for_model(target.model)
            price = resolved[1] if resolved is not None else None
        return (
            model_pricing(price, source_rates=source_rates) if price is not None else None,
            model_price_is_billable(price),
        )

    priced: set[str] = set()
    prices: dict[str, ModelPricing] = {}
    for model, targets in targets_by_model.items():
        try:
            resolved = [target_price(target) for target in targets]
            if resolved and all(billable for _, billable in resolved):
                priced.add(model)
            first = resolved[0][0] if resolved else None
            if first is not None and all(price == first for price, _ in resolved):
                prices[model] = first
        except Exception:
            logger.warning("shared_api_key_listing_price_check_failed model=%s", model, exc_info=True)
    return ListedModelPrices(billable=frozenset(priced), pricing=prices)


async def priced_listed_models(
    models: Sequence[str],
    *,
    routing_entries: tuple[SidecarRoutingEntry, ...],
    sources_by_model: Mapping[str, ModelSource],
    aliases: Mapping[str, ModelAliasPool],
) -> frozenset[str]:
    """The ids a shared key would be served, using the catalog's price resolver."""
    result = await listed_model_prices(
        models, routing_entries=routing_entries, sources_by_model=sources_by_model, aliases=aliases
    )
    return result.billable
