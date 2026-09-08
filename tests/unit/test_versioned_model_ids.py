from __future__ import annotations

import pytest

from app.core.usage.model_ids import resolve_versioned_model_id
from app.core.usage.pricing import ModelPrice, get_pricing_for_model

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
