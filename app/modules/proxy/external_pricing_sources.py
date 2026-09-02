"""Wire each participating integration into external price resolution.

Core owns pricing; each integration declares how to reach its own catalog and
routing configuration. Registration happens once at startup so the pricing layer
never imports a sidecar module.

Three integrations participate, and they contribute different things:

OrcaRouter and OpenRouter
    Publish per-token rates on their own ``/models`` listing, so they supply a
    priced serving catalog. That catalog is authoritative for ids they serve, which
    matters because they list overlapping ids at different prices.

CLIProxyAPI
    Publishes a model listing with no prices at all, so it supplies **no** price
    catalog -- only its configured routing prefixes and the operator's alias map.
    That is exactly what turns ``cc/claude-fable-5`` into the ``claude-fable-5``
    the vendor's catalog knows, instead of stripping ``cc/`` blindly and hoping the
    remainder means something.

Ollama and OmniRoute are absent on purpose: local inference has no published
external rate, and OmniRoute does not identify a catalog model to price.
"""

from __future__ import annotations

import logging

from app.core.clients.claude_sidecar import SidecarModel, SidecarPrefix
from app.core.types import JsonValue
from app.core.usage.external_pricing.catalogs import (
    PROVIDER_CLIPROXY,
    PROVIDER_OPENROUTER,
    PROVIDER_ORCAROUTER,
    catalog_from_sidecar_models,
)
from app.core.usage.external_pricing.service import ServingContext, register_serving_context_loader
from app.core.usage.pricing import ModelPrice
from app.modules.proxy.model_aliasing import load_model_aliases

logger = logging.getLogger(__name__)


def _prefix_pairs(prefixes: tuple[SidecarPrefix, ...]) -> tuple[tuple[str, bool], ...]:
    return tuple((prefix.prefix, prefix.strip) for prefix in prefixes)


def _catalog_rows(models: list[SidecarModel]) -> list[tuple[str, ModelPrice | None, JsonValue]]:
    """Carry each model's raw ``pricing`` block alongside its parsed price.

    Without the raw block an id the sidecar listed with rate fields this build
    could not parse is indistinguishable from one it listed with no rates, and the
    resolver would settle the former as permanently not token priced.
    """

    rows: list[tuple[str, ModelPrice | None, JsonValue]] = []
    for model in models:
        raw_pricing = model.raw.get("pricing") if model.raw is not None else None
        rows.append((model.id, model.pricing, raw_pricing))
    return rows


async def _load_orcarouter_context(_provider: str) -> ServingContext | None:
    from app.core.clients.orcarouter_sidecar import (
        ORCAROUTER_PRICING_PROVIDER,
        OrcaRouterSidecarClient,
    )
    from app.modules.proxy.orcarouter_sidecar_dispatch import load_orcarouter_sidecar_config

    config = await load_orcarouter_sidecar_config()
    if config is None:
        # The loader could not read dashboard settings. Nothing is known about
        # this integration, least of all whether the operator turned it off, so
        # this is a failure to consult and callers must preserve prior values.
        return None
    if not config.enabled:
        # Switched off, not unreachable. Returning ``None`` here would make the
        # maintenance pass report a catalog failure that never happened.
        return ServingContext.disabled(
            aliases=await load_model_aliases(),
            prefixes=_prefix_pairs(config.prefixes),
        )
    # ``list_models`` rather than ``list_models_cached``: the cached variant
    # degrades a failed fetch to an empty list, which a resolver cannot tell from
    # a catalogue that genuinely lists nothing. Raising lets the caller preserve
    # prior values. Lookups are rare by construction, so the extra fetch is not on
    # any hot path.
    models = await OrcaRouterSidecarClient(config).list_models()
    return ServingContext(
        catalog=catalog_from_sidecar_models(
            ORCAROUTER_PRICING_PROVIDER,
            _catalog_rows(list(models)),
        ),
        aliases=await load_model_aliases(),
        prefixes=_prefix_pairs(config.prefixes),
    )


async def _load_openrouter_context(_provider: str) -> ServingContext | None:
    from app.core.clients.openrouter_sidecar import (
        OPENROUTER_PRICING_PROVIDER,
        OpenRouterSidecarClient,
    )
    from app.modules.proxy.openrouter_sidecar_dispatch import load_openrouter_sidecar_config

    config = await load_openrouter_sidecar_config()
    if config is None:
        return None
    if not config.enabled:
        return ServingContext.disabled(
            aliases=await load_model_aliases(),
            prefixes=_prefix_pairs(config.prefixes),
        )
    models = await OpenRouterSidecarClient(config).list_models()
    return ServingContext(
        catalog=catalog_from_sidecar_models(
            OPENROUTER_PRICING_PROVIDER,
            _catalog_rows(list(models)),
        ),
        aliases=await load_model_aliases(),
        prefixes=_prefix_pairs(config.prefixes),
    )


async def _load_cliproxy_context(_provider: str) -> ServingContext | None:
    """Routing identity for CLIProxyAPI ids; no price catalog.

    CLIProxyAPI proxies other vendors' models and publishes no rates, so supplying
    an unpriced catalog here would make every id resolve to "listed but not token
    priced" and stop the search before the vendor's real catalog is consulted.
    Contributing only the prefixes and aliases lets ``cc/claude-fable-5`` reduce to
    ``claude-fable-5`` and then match the vendor entry that actually carries a
    price.
    """

    from app.modules.proxy.claude_sidecar_dispatch import load_sidecar_config

    config = await load_sidecar_config()
    if config is None:
        return None
    if not config.enabled:
        return ServingContext.disabled(
            aliases=await load_model_aliases(),
            prefixes=_prefix_pairs(config.prefixes),
        )
    return ServingContext(
        catalog=None,
        aliases=await load_model_aliases(),
        prefixes=_prefix_pairs(config.prefixes),
        # Not a fetch failure: this integration has no rates to publish. Saying so
        # explicitly is what lets maintenance treat the pricing reference as the
        # authoritative answer for these ids instead of preserving stale rates
        # forever behind a phantom "catalog unavailable".
        publishes_price_catalog=False,
    )


def register_external_pricing_sources() -> None:
    """Register every participating integration. Idempotent."""

    register_serving_context_loader(PROVIDER_ORCAROUTER, _load_orcarouter_context)
    register_serving_context_loader(PROVIDER_OPENROUTER, _load_openrouter_context)
    register_serving_context_loader(PROVIDER_CLIPROXY, _load_cliproxy_context)
