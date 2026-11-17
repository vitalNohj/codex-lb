from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.exceptions import ProxyModelNotAllowed
from app.core.usage import pricing_catalog
from app.core.usage.logs import calculated_cost_from_log
from app.core.usage.model_ids import resolve_versioned_model_id
from app.core.usage.pricing import (
    DEFAULT_PRICING_MODELS,
    ModelPrice,
    UsageTokens,
    calculate_cost_from_usage,
    effective_cache_write_rate,
    effective_rates,
    get_pricing_for_model,
)
from app.modules.proxy.model_pricing import model_pricing
from app.modules.proxy.request_policy import validate_model_access
from app.modules.proxy.sidecar_routing import SidecarRoutingEntry, resolve_sidecar_route

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("model,scale", [("gpt-6.2-sol", 1), ("gpt-6.2-astra", 4)])
@pytest.mark.parametrize("input_tokens", [1000, 272_000, 272_001, 872_000])
@pytest.mark.parametrize("tier,multiplier", [(None, 1), ("default", 1), ("priority", 2), ("fast", 2), ("batch", 0.5)])
def test_gpt62_published_rates_and_settlement(model, scale, input_tokens, tier, multiplier):
    resolved = get_pricing_for_model(model)
    assert resolved is not None
    price = resolved[1]
    long = input_tokens > 272_000
    factor = scale * multiplier
    expected = (4 * factor, 0.2 * factor, 15 * factor) if long else (2 * factor, 0.1 * factor, 10 * factor)
    write = (5 if long else 2.5) * factor
    write_12h = (10 if long else 5) * factor
    usage = UsageTokens(input_tokens, 97, cached_input_tokens=211, cache_write_input_tokens=83)
    assert effective_rates(usage, price, service_tier=tier) == pytest.approx(expected)
    assert effective_cache_write_rate(usage, price, service_tier=tier, input_rate=expected[0]) == write
    assert (
        effective_cache_write_rate(usage, price, service_tier=tier, input_rate=expected[0], retention_12h=True)
        == write_12h
    )
    expected_cost = (
        (input_tokens - 211 - 83) * expected[0] + 211 * expected[1] + 97 * expected[2] + 83 * write
    ) / 1_000_000
    assert calculate_cost_from_usage(usage, price, service_tier=tier) == pytest.approx(expected_cost)
    log = SimpleNamespace(
        model=model,
        service_tier=tier,
        input_tokens=input_tokens,
        output_tokens=97,
        cached_input_tokens=211,
        cache_write_input_tokens=83,
        reasoning_tokens=0,
    )
    assert calculated_cost_from_log(log) == pytest.approx(expected_cost)

    listed = model_pricing(price).model_dump()
    assert "flex" not in listed
    rates = listed["priority" if tier == "fast" else tier] if tier in ("priority", "fast", "batch") else listed
    if long:
        rates = rates["long_context"]
        assert rates["threshold_tokens"] == 272_000
    assert (rates["input"], rates["cache_read"], rates["output"]) == pytest.approx(expected)
    assert rates["cache_write"] == write
    assert rates["cache_write_12h"] == write_12h


@pytest.mark.parametrize("model", ["gpt-6.2-sol", "gpt-6.2-astra"])
def test_gpt62_rates_have_one_authority_even_after_catalog_refresh(monkeypatch, model):
    monkeypatch.setattr(pricing_catalog, "_prices", None)
    assert pricing_catalog.get_active_prices()[model] is DEFAULT_PRICING_MODELS[model]
    pricing_catalog.install_prices(
        {model: ModelPrice(input_per_1m=999, output_per_1m=999, flex_input_per_1m=1, flex_output_per_1m=1)}
    )
    assert get_pricing_for_model(model) == (model, DEFAULT_PRICING_MODELS[model])
    resolved = get_pricing_for_model(model)
    assert resolved is not None
    assert "flex" not in model_pricing(resolved[1]).model_dump()
    # A stale alias row cannot create a second authority for the same model.
    alias = f"codex/{model}-2026-11-17"
    pricing_catalog.install_prices({alias: ModelPrice(input_per_1m=999, output_per_1m=999)})
    assert get_pricing_for_model(alias) == (model, DEFAULT_PRICING_MODELS[model])


@pytest.mark.parametrize("family", ["sol", "astra"])
@pytest.mark.parametrize("prefix", ["", "codex/", "openai/", "cc/", "cp-", "cp_"])
@pytest.mark.parametrize("suffix", ["", "-2026-11-17", "-20261117", "-high", "-2026-11-17-fast"])
def test_gpt62_names_resolve_only_to_their_own_price(family, prefix, suffix):
    canonical = f"gpt-6.2-{family}"
    requested = (prefix + canonical + suffix).upper()
    assert resolve_versioned_model_id(requested) == (canonical if prefix in ("", "codex/", "openai/") else None)
    resolved = get_pricing_for_model(requested)
    assert resolved is not None
    assert resolved[0] == canonical
    assert resolved[1] is DEFAULT_PRICING_MODELS[canonical]
    older = {key: value for key, value in DEFAULT_PRICING_MODELS.items() if not key.startswith("gpt-6.2-")}
    assert get_pricing_for_model(requested, older) is None


@pytest.mark.parametrize(
    "requested",
    [
        "gpt-6.2-sol-pro",
        "gpt-6.2-astra-law",
        "gpt-6.2-sol-other",
        "unrelated/gpt-6.2-astra",
        "prefix-gpt-6.2-sol",
        "gpt-6-2-sol",
        "gpt-6.2-luna",
        "cc/cc/gpt-6.2-sol",
    ],
)
def test_gpt62_names_do_not_swallow_other_models(requested):
    assert resolve_versioned_model_id(requested) is None
    assert get_pricing_for_model(requested, DEFAULT_PRICING_MODELS) is None


@pytest.mark.parametrize("family", ["sol", "astra"])
@pytest.mark.parametrize("outer", ["cc/", "cp-", "cp_"])
@pytest.mark.parametrize("inner", ["cc/", "cp-", "cp_"])
def test_gpt62_authorization_never_strips_a_second_routing_prefix(family, outer, inner):
    canonical = f"gpt-6.2-{family}"
    entries = (
        SidecarRoutingEntry(
            provider="claude",
            prefixes=tuple(SidecarPrefix(prefix=p, strip=True) for p in ("cc/", "cp-", "cp_")),
            full_models=(canonical,),
        ),
    )
    key = SimpleNamespace(allowed_models=[canonical], allowed_reasoning_efforts=None)
    # Both the grant and the legitimate prefix route to the same provider and
    # the same wire model. A second prefix is part of a different wire id.
    validate_model_access(cast(Any, key), outer + canonical, routing_entries=entries)
    requested = outer + inner + canonical
    route = resolve_sidecar_route(requested, entries)
    assert route is not None
    assert route.wire_model == inner + canonical
    with pytest.raises(ProxyModelNotAllowed):
        validate_model_access(cast(Any, key), requested, routing_entries=entries)
