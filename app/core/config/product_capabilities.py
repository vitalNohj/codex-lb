"""Centralized product-capability boundary for optional integrations.

A capability is a *product* decision, not an operator setting: when a
capability is disabled the integration must be invisible and unreachable
regardless of persisted dashboard settings, environment variables, or
migrated database columns. Dormant implementation modules stay in the tree so
the capability can be re-enabled by flipping one constant here.

The server source of truth lives in :data:`DISABLED_PRODUCT_CAPABILITIES`.
Server code asks :func:`is_capability_enabled` (or the named helper) at every
externally reachable path, and ``GET /api/runtime/capabilities`` exposes the
state to API clients. The bundled dashboard mirrors this boundary in its
compile-time capability constants because it ships with the server.
"""

from __future__ import annotations

from typing import Final

#: Capability key for the OmniRoute sidecar integration.
OMNIROUTE: Final = "omniroute"

#: Every capability the product knows about, enabled or not.
KNOWN_PRODUCT_CAPABILITIES: Final[tuple[str, ...]] = (OMNIROUTE,)

#: Capabilities disabled at the product level. Remove an entry here and enable
#: the matching bundled-dashboard constant to re-enable an integration.
DISABLED_PRODUCT_CAPABILITIES: Final[frozenset[str]] = frozenset({OMNIROUTE})


def is_capability_enabled(capability: str) -> bool:
    """Return whether ``capability`` is enabled as a product integration."""

    return capability not in DISABLED_PRODUCT_CAPABILITIES


def omniroute_enabled() -> bool:
    """Return whether the OmniRoute integration is enabled as a product."""

    return is_capability_enabled(OMNIROUTE)


def enabled_product_capabilities() -> dict[str, bool]:
    """Return the enabled state of every known capability, for the dashboard."""

    return {capability: is_capability_enabled(capability) for capability in KNOWN_PRODUCT_CAPABILITIES}
