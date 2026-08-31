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


# ``RequestLog.source`` values written by the dispatchers that participate. The
# request log records the serving integration, not the pricing provider key, so a
# reader that needs to know whether the resolver owns a row's cost matches on
# these rather than inferring it from a column that may legitimately be NULL.
EXTERNAL_PRICED_LOG_SOURCES: frozenset[str] = frozenset(
    {
        "openrouter_sidecar",
        "orcarouter_sidecar",
        "claude_sidecar",
    }
)


def is_external_priced_provider(provider: str | None) -> bool:
    return bool(provider) and provider.strip().lower() in EXTERNAL_PRICED_PROVIDERS


def is_external_priced_log_source(source: str | None) -> bool:
    return bool(source) and source.strip().lower() in EXTERNAL_PRICED_LOG_SOURCES
