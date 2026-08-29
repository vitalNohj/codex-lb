"""Shared, persistent model-price resolution for external integrations.

One owner for pricing records and resolution state across OpenRouter, OrcaRouter,
and CLIProxyAPI. Ollama and OmniRoute do not participate.

Layers, each with one job:

``resolution``
    Pure mapping from an incoming model id to a catalog id, abstaining whenever
    more than one catalog model plausibly matches.
``catalogs``
    Authoritative structured catalog sources and their parsing.
``store``
    Durable record of every mapping, its rates, its provenance, and its bounded
    retry state.
``service``
    The cache-first request path and the deduplicated background lookup.
``maintenance``
    One explicit, idempotent refresh pass. No schedule.
"""

from __future__ import annotations

from app.core.usage.external_pricing.catalogs import (
    EXTERNAL_PRICED_PROVIDERS,
    PROVIDER_CLIPROXY,
    PROVIDER_OPENROUTER,
    PROVIDER_ORCAROUTER,
    is_external_priced_provider,
)
from app.core.usage.external_pricing.service import (
    CalculatedCost,
    ServingContext,
    calculated_cost_for_request,
    register_serving_context_loader,
)

__all__ = [
    "EXTERNAL_PRICED_PROVIDERS",
    "PROVIDER_CLIPROXY",
    "PROVIDER_OPENROUTER",
    "PROVIDER_ORCAROUTER",
    "CalculatedCost",
    "ServingContext",
    "calculated_cost_for_request",
    "is_external_priced_provider",
    "register_serving_context_loader",
]
