"""The centralized product-capability boundary.

One constant decides whether an optional integration exists as a product. The
externally callable server paths and the dashboard both read this answer, so a
single edit re-enables the integration everywhere.
"""

from __future__ import annotations

import pytest

from app.core.config.product_capabilities import (
    KNOWN_PRODUCT_CAPABILITIES,
    OMNIROUTE,
    enabled_product_capabilities,
    is_capability_enabled,
    omniroute_enabled,
)

pytestmark = pytest.mark.unit


def test_omniroute_is_disabled_as_a_product_capability() -> None:
    assert omniroute_enabled() is False
    assert is_capability_enabled(OMNIROUTE) is False


def test_capabilities_the_product_does_not_gate_are_enabled() -> None:
    # Sidecar providers with no capability entry must stay routable.
    for provider in ("claude", "openrouter", "orcarouter", "ollama"):
        assert is_capability_enabled(provider) is True


def test_reported_capabilities_cover_every_known_capability() -> None:
    reported = enabled_product_capabilities()

    assert set(reported) == set(KNOWN_PRODUCT_CAPABILITIES)
    assert reported[OMNIROUTE] is False
