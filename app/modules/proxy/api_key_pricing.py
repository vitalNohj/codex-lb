"""Whether a request's model has a price on the route that will serve it.

A shared API key with a cost budget refuses a model it cannot meter (see
``ApiKeysService.enforce_limits_for_request``). Only the dispatch path knows
which price table settles a request, so each one hands admission the check that
matches its own settlement:

* Codex, Ollama, OmniRoute, images, and transcription settle from the static
  price table, which is admission's default.
* Sidecars that take part in external price resolution settle from the
  persisted external price store, under their pricing provider.
* Model sources settle from the source's own per-model rates.
* Requests that never charge a cost (model listings, file uploads) are always
  allowed.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.core.usage.external_pricing import is_external_priced_provider, model_has_known_price
from app.core.usage.external_pricing.providers import PROVIDER_CLIPROXY
from app.db.models import ModelSource
from app.modules.api_keys.service import ModelPricedCheck, static_model_is_priced
from app.modules.model_sources.catalog import source_model_has_price

# Sidecar routes whose pricing provider is not named like the route. ``claude``
# is CLIProxyAPI, which prices everything it relays under ``cliproxy``.
_ROUTE_PRICING_PROVIDERS: dict[str, str] = {"claude": PROVIDER_CLIPROXY}


async def route_model_is_priced(provider: str, model: str) -> bool:
    """Whether settlement on sidecar route ``provider`` can price ``model``."""
    pricing_provider = _ROUTE_PRICING_PROVIDERS.get(provider, provider)
    if not is_external_priced_provider(pricing_provider):
        # Ollama and OmniRoute take no part in external pricing; their
        # settlement prices the model from the static table.
        return static_model_is_priced(model)
    return await model_has_known_price(provider=pricing_provider, model=model)


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
