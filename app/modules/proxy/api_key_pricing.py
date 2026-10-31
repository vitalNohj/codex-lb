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
    billable_price_snapshot,
    is_external_priced_provider,
    model_has_billable_price,
)
from app.core.usage.external_pricing.providers import PROVIDER_CLIPROXY
from app.db.models import ModelSource
from app.modules.api_keys.service import ModelPricedCheck, static_model_is_priced
from app.modules.model_sources.catalog import source_model_has_price
from app.modules.proxy.model_aliasing import resolve_model_alias_pool
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


async def priced_listed_models(
    models: Sequence[str],
    *,
    routing_entries: tuple[SidecarRoutingEntry, ...],
    sources_by_model: Mapping[str, ModelSource],
    aliases: Mapping[str, ModelAliasPool],
) -> frozenset[str]:
    """The ids in ``models`` a shared key would be served if it asked for them by name.

    Every target an id can land on must be priced at a real rate on the route
    that serves it. The external prices for the whole listing are read in one
    query. Anything that fails hides the id: a listing must never show a shared
    key a model it would be refused.
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
        external_is_billable = await billable_price_snapshot(external_keys)
    except Exception:
        logger.warning("shared_api_key_listing_price_check_failed count=%d", len(models), exc_info=True)
        return frozenset()

    def target_is_priced(target: _ListedTarget) -> bool:
        if target.pricing_provider is not None and is_external_priced_provider(target.pricing_provider):
            return external_is_billable is not None and external_is_billable(target.pricing_provider, target.model)
        if target.pricing_provider is None and target.source is not None:
            return source_model_has_price(target.source, target.model, accepts_audio_rate=False)
        # Ollama and OmniRoute settle from the static table, as does every
        # model no sidecar or source owns.
        return static_model_is_priced(target.model)

    priced: set[str] = set()
    for model, targets in targets_by_model.items():
        try:
            if all(target_is_priced(target) for target in targets):
                priced.add(model)
        except Exception:
            logger.warning("shared_api_key_listing_price_check_failed model=%s", model, exc_info=True)
    return frozenset(priced)
