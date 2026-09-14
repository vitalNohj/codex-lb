"""OpenCode Go's price fallback, through the composed pricing lane.

This is the captain's requirement applied to Go specifically: *"when a model is
detected and we don't have cost, it looks up on OpenRouter or on OrcaRouter as a
fallback ... and tries to get a price for input and output for that model."*

Go is the hardest case for that machinery and the reason it needs its own test.
`GET /zen/go/v1/models` returns `{id, object, created, owned_by}` with **no
pricing block at all**, so Go contributes no price catalog. Its loader therefore
declares `publishes_price_catalog=False` rather than handing over an empty
catalog - an empty one would settle every Go id as "listed but not token priced"
and stop the search before any catalog carrying a rate is consulted.

The pricing lane has since added a lazy secondary reference (`bdb11880`): the
secondary is now fetched only when the primary sources did not already settle
the id by an `exact` match. That optimization is correct in general, but Go's
whole fallback depends on *not* being settled by the serving catalog, so the
interaction is worth pinning directly rather than inferring from either lane's
tests.

Composed inputs: backend `119a8cb2`, pricing `bdb11880`. Everything runs from
the delivered repository - no sibling refs, no private documents.
"""

from __future__ import annotations

import pytest

from app.core.usage.external_pricing.providers import (
    EXTERNAL_PRICED_PROVIDERS,
    PROVIDER_OPENCODE_GO,
    external_priced_provider_for_log_source,
    is_external_priced_provider,
)
from app.core.usage.external_pricing.service import (
    ServingContext,
    load_serving_context,
    reset_serving_context_loaders,
)
from app.modules.proxy.external_pricing_sources import register_external_pricing_sources

pytestmark = pytest.mark.integration

GO_LOG_SOURCE = "opencode_go_sidecar"


@pytest.fixture(autouse=True)
def _restore_loaders():
    yield
    reset_serving_context_loaders()
    register_external_pricing_sources()


def test_go_is_registered_as_an_externally_priced_provider():
    """Both halves, or a Go request cannot be traced from its log row to its cost."""
    assert PROVIDER_OPENCODE_GO == "opencode_go"
    assert is_external_priced_provider(PROVIDER_OPENCODE_GO)
    assert PROVIDER_OPENCODE_GO in EXTERNAL_PRICED_PROVIDERS
    assert external_priced_provider_for_log_source(GO_LOG_SOURCE) == PROVIDER_OPENCODE_GO


@pytest.mark.asyncio
async def test_the_go_loader_declares_no_catalog_rather_than_an_empty_one(async_client):
    """The load-bearing distinction for Go's entire fallback.

    ``catalog=None`` with ``publishes_price_catalog=False`` means "this
    integration has no rates to give, ask elsewhere". An empty catalog would
    mean "asked, and it lists nothing", which settles the id as unpriced and
    ends the search. The two are one boolean apart and produce opposite
    outcomes, so this asserts the boolean rather than trusting the comment.

    ``async_client`` is taken for its app lifespan, which owns the HTTP client
    the loader leases.
    """
    del async_client
    register_external_pricing_sources()

    context = await load_serving_context(PROVIDER_OPENCODE_GO)

    assert isinstance(context, ServingContext)
    assert context.catalog is None
    assert context.publishes_price_catalog is False, (
        "the Go loader claims to publish a price catalog; every Go id would then "
        "settle as 'listed but not token priced' and never reach a catalog that "
        "carries a real rate"
    )
    # Not a fetch failure either: a failure must preserve prior values, and this
    # is a settled fact about the provider.
    assert context.serving_catalog_missing is False


@pytest.mark.asyncio
async def test_a_disabled_go_integration_is_reported_as_disabled_not_as_a_failure(async_client):
    """Switched off is not the same as unreachable.

    Reporting a disabled integration as a catalog failure would put a permanent
    error in front of an operator who turned it off deliberately.
    """
    del async_client
    register_external_pricing_sources()

    context = await load_serving_context(PROVIDER_OPENCODE_GO)

    assert context is not None
    # Go ships disabled, so this is the default path.
    assert context.integration_enabled is False
    assert context.serving_catalog_missing is False


@pytest.mark.asyncio
async def test_the_go_prefix_is_contributed_so_a_prefixed_id_can_reduce_to_a_catalog_id(async_client, monkeypatch):
    """``opencode-go/glm-5.3`` must be able to reduce to ``glm-5.3``.

    Without the routing prefix reaching the resolver, the prefixed id would never
    match any catalog entry and Go would be permanently unpriced regardless of
    what the reference lists.
    """
    del async_client
    from app.core.clients.claude_sidecar import SidecarPrefix
    from app.core.clients.opencode_go_sidecar import OpenCodeGoSidecarConfig

    config = OpenCodeGoSidecarConfig(
        enabled=True,
        base_url="https://opencode.ai/zen/go/v1",
        api_key="sk-go-pricing-Zq7SvT2pLm9K",
        prefixes=(SidecarPrefix(prefix="opencode-go/", strip=True),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=("glm-5.3",),
    )

    async def _load_config():
        return config

    monkeypatch.setattr(
        "app.modules.proxy.opencode_go_sidecar_dispatch.load_opencode_go_sidecar_config",
        _load_config,
    )
    register_external_pricing_sources()

    context = await load_serving_context(PROVIDER_OPENCODE_GO)

    assert context is not None
    assert ("opencode-go/", True) in tuple(context.prefixes), (
        f"the Go routing prefix did not reach the pricing resolver: {context.prefixes}"
    )
    # Still no catalog, even while enabled and configured: Go never publishes rates.
    assert context.catalog is None
    assert context.publishes_price_catalog is False


def test_the_lazy_secondary_reference_cannot_short_circuit_an_unsettled_go_id():
    """Pins the interaction between Go's fallback and the pricing optimization.

    ``bdb11880`` skips the secondary reference when the primary sources already
    settled the id by an ``exact`` match. Go contributes no catalog at all, so a
    Go id can never be settled that way, and the skip must never apply to it.

    Asserted on the predicate itself rather than through a full lookup, because
    this is precisely the branch a future refactor could widen from "exact" to
    "any settled outcome" - which would silently strand every Go id unpriced.
    """
    from app.core.usage.external_pricing.resolution import Resolution, ResolutionOutcome
    from app.core.usage.external_pricing.service import _is_exactly_settled

    def _resolution(outcome: ResolutionOutcome, step: str | None) -> Resolution:
        return Resolution(outcome=outcome, step=step)

    # An exact hit may skip the secondary reference.
    assert _is_exactly_settled(_resolution(ResolutionOutcome.RESOLVED, "exact")) is True
    assert _is_exactly_settled(_resolution(ResolutionOutcome.RESOLVED, "prefix+exact")) is True

    # Everything a Go id can actually produce must NOT skip it. Go publishes no
    # catalog, so its ids arrive unresolved and must continue to the reference.
    assert _is_exactly_settled(_resolution(ResolutionOutcome.UNRESOLVED, None)) is False
    assert _is_exactly_settled(_resolution(ResolutionOutcome.RESOLVED, "normalized")) is False
    assert _is_exactly_settled(_resolution(ResolutionOutcome.RESOLVED, "vendor_qualified")) is False
    assert _is_exactly_settled(_resolution(ResolutionOutcome.AMBIGUOUS, None)) is False


def test_a_go_cost_is_a_list_price_estimate_and_never_a_subscription_charge():
    """Firm rule from the contract, and a bug two other projects shipped.

    Go is a flat $10/month subscription that reports no billed cost, so any
    figure codex-lb derives is arithmetic over someone else's published rates -
    a usage estimate, never the amount charged. ``cost_source`` is what keeps
    those distinguishable on the request log and in the dashboard.
    """
    from app.db.models import CostSource

    # The two provenances must remain distinct values; collapsing them would
    # make an estimate indistinguishable from a real debit.
    assert CostSource.CATALOG_CALCULATED.value != CostSource.UPSTREAM_BILLED.value
    assert CostSource.CATALOG_CALCULATED.value == "catalog_calculated"
