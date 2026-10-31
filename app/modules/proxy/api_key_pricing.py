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
  ``listed_model_is_priced`` says it would be refused.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from app.core.usage.external_pricing import is_external_priced_provider, model_has_billable_price
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


async def listed_model_is_priced(
    model: str,
    *,
    routing_entries: tuple[SidecarRoutingEntry, ...],
    sources_by_model: Mapping[str, ModelSource],
    aliases: Mapping[str, ModelAliasPool],
) -> bool:
    """Whether a shared key would be served ``model`` if it asked for it by name.

    Mirrors admission: the name resolves through the alias map first, and every
    target it can land on must be priced on the route that serves it, the
    sidecar that owns it, else the model source listing it, else the static
    table. A target that names no route is judged by the static table, which
    can only hide more. A lookup that fails hides the model.
    """

    try:
        resolved = resolve_model_alias_pool(model, aliases)
        pooled = resolved is not None and resolved.is_pool
        targets = resolved.targets if resolved is not None else (model,)
        for target in targets:
            decision = (
                resolve_sidecar_pool_target(target, routing_entries)
                if pooled
                else resolve_sidecar_route(target, routing_entries)
            )
            if decision is not None:
                priced = await route_model_is_priced(decision.provider, target)
            elif (source := sources_by_model.get(target)) is not None:
                priced = source_model_has_price(source, target, accepts_audio_rate=False)
            else:
                priced = static_model_is_priced(target)
            if not priced:
                return False
        return True
    except Exception:
        logger.warning("shared_api_key_listing_price_check_failed model=%s", model, exc_info=True)
        return False
