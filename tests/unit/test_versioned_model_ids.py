from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.core.exceptions import ProxyModelNotAllowed
from app.core.usage.model_ids import resolve_versioned_model_id
from app.core.usage.pricing import DEFAULT_PRICING_MODELS, ModelPrice, get_pricing_for_model
from app.modules.proxy.request_policy import validate_model_access

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("requested", "canonical"),
    [
        ("gpt-6-astra", "gpt-6-astra"),
        ("codex/gpt-6-astra-2026-09-03", "gpt-6-astra"),
        ("GPT-6-ASTRA-20260903", "gpt-6-astra"),
        ("cc/claude-fable-5.1-thinking-max", "claude-fable-5-1"),
        ("cp_claude-fable-5-1", "claude-fable-5-1"),
        ("claude-fable-5-1-20260901", "claude-fable-5-1"),
        ("claude-fable-5", None),
        ("claude-fable-5-10", None),
        ("claude-fable-5.10", None),
        ("claude-fable-5-1-unrelated", None),
        ("notclaude-fable-5-1", None),
        ("gpt-6-astra-pro", None),
        ("unrelated/gpt-6-astra", None),
    ],
)
def test_versioned_identity_is_bounded(requested: str, canonical: str | None) -> None:
    assert resolve_versioned_model_id(requested) == canonical


def test_versioned_pricing_uses_supplied_rates_not_an_embedded_price() -> None:
    price = ModelPrice(input_per_1m=2, output_per_1m=3)
    assert get_pricing_for_model("cc/claude-fable-5.1", {"claude-fable-5-1": price}) == (
        "claude-fable-5-1",
        price,
    )


def test_pricing_falls_back_to_the_family_when_the_version_is_absent() -> None:
    """A catalog without the version must still price the request, not drop its cost."""
    family = ModelPrice(input_per_1m=7, output_per_1m=11)
    assert get_pricing_for_model("cc/claude-fable-5-1", {"claude-fable-5": family}) == (
        "claude-fable-5",
        family,
    )
    assert get_pricing_for_model("gpt-6-astra", {"claude-fable-5": family}) is None
    assert get_pricing_for_model("cc/claude-fable-5-1", DEFAULT_PRICING_MODELS)[0] == "claude-fable-5-1"


@pytest.mark.parametrize(
    "requested",
    ["cc/claude-fable-5-1", "claude-fable-5.1", "claude-fable-5-1-thinking-max", "codex/gpt-6-astra"],
)
def test_family_allowlist_does_not_admit_a_separately_priced_version(requested: str) -> None:
    key = SimpleNamespace(allowed_models=["claude-fable-5"], allowed_reasoning_efforts=None)

    with pytest.raises(ProxyModelNotAllowed):
        validate_model_access(cast(Any, key), requested)


@pytest.mark.parametrize("requested", ["cc/claude-fable-5-1", "claude-fable-5.1"])
def test_an_allowlist_naming_the_version_still_admits_it(requested: str) -> None:
    key = SimpleNamespace(allowed_models=["claude-fable-5-1"], allowed_reasoning_efforts=None)

    validate_model_access(cast(Any, key), requested)


def test_family_allowlist_still_admits_the_family() -> None:
    key = SimpleNamespace(allowed_models=["claude-fable-5"], allowed_reasoning_efforts=None)

    validate_model_access(cast(Any, key), "cc/claude-fable-5")
