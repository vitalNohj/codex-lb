"""Which serving integrations participate in external price resolution.

A leaf module on purpose: both the pricing package and the reference-cost
(savings) path need this answer, and neither may drag the other's imports in to
get it.

Ollama and OmniRoute are excluded by design. Local inference has no published
external rate, and OmniRoute's routing does not identify a catalog model to
price, so their request-log cost stays ``--`` and their reference cost keeps
using the runtime overlay it always used.
"""

from __future__ import annotations

PROVIDER_OPENROUTER = "openrouter"
PROVIDER_ORCAROUTER = "orcarouter"
PROVIDER_CLIPROXY = "cliproxy"

EXTERNAL_PRICED_PROVIDERS: frozenset[str] = frozenset(
    {
        PROVIDER_OPENROUTER,
        PROVIDER_ORCAROUTER,
        PROVIDER_CLIPROXY,
    }
)


def is_external_priced_provider(provider: str | None) -> bool:
    return bool(provider) and provider.strip().lower() in EXTERNAL_PRICED_PROVIDERS
