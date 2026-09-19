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
PROVIDER_NVIDIA = "nvidia"
PROVIDER_ORCAROUTER = "orcarouter"
PROVIDER_CLIPROXY = "cliproxy"
#: OpenCode Go. Participates so its ids reach the resolver, but it publishes no
#: rates of its own: ``GET /zen/go/v1/models`` carries no pricing block at all.
#: Its cost is always a list-price *estimate*, never subscription spend.
PROVIDER_OPENCODE_GO = "opencode_go"

EXTERNAL_PRICED_PROVIDERS: frozenset[str] = frozenset(
    {
        PROVIDER_OPENROUTER,
        PROVIDER_NVIDIA,
        PROVIDER_ORCAROUTER,
        PROVIDER_CLIPROXY,
        PROVIDER_OPENCODE_GO,
    }
)


# Providers that bill per request and report that debit on the response. For
# them a reported ``0`` is a real billed amount -- an OpenRouter ``:free`` model
# is debited exactly nothing -- and must be stored as authoritative spend.
#
# A provider absent from this set does not bill per request. A flat-rate
# subscription upstream still emits a ``usage.cost`` field, and it is ``0``
# because there is no per-request debit to report, not because this request was
# free. Recording that as ``upstream_billed`` states, with the highest available
# provenance, that the request is known to have cost nothing -- which outranks the
# calculated list price, blocks the resolver's answer from ever being shown, and
# reports a subscription's usage as free traffic. Two other projects shipped that
# exact conflation and had to fix it.
#
# Membership is about billing identity, not about whether the number parses, so
# it is declared here beside the provider keys rather than inferred at the call
# site from a value that looks plausible.
PER_REQUEST_BILLED_PROVIDERS: frozenset[str] = frozenset(
    {
        PROVIDER_OPENROUTER,
        PROVIDER_ORCAROUTER,
    }
)


# ``RequestLog.source`` values written by the dispatchers that participate. The
# request log records the serving integration, not the pricing provider key, so a
# reader that needs to know whether the resolver owns a row's cost matches on
# these rather than inferring it from a column that may legitimately be NULL.
EXTERNAL_PRICED_LOG_SOURCES: frozenset[str] = frozenset(
    {
        "openrouter_sidecar",
        "nvidia_sidecar",
        "orcarouter_sidecar",
        "claude_sidecar",
        "opencode_go_sidecar",
    }
)

_LOG_SOURCE_PROVIDERS: dict[str, str] = {
    "openrouter_sidecar": PROVIDER_OPENROUTER,
    "nvidia_sidecar": PROVIDER_NVIDIA,
    "orcarouter_sidecar": PROVIDER_ORCAROUTER,
    "claude_sidecar": PROVIDER_CLIPROXY,
    "opencode_go_sidecar": PROVIDER_OPENCODE_GO,
}


def is_external_priced_provider(provider: str | None) -> bool:
    return bool(provider) and provider.strip().lower() in EXTERNAL_PRICED_PROVIDERS


def reports_per_request_billed_cost(provider: str | None) -> bool:
    """Whether an amount this provider reports is an actual per-request debit.

    ``False`` means any cost field on its responses describes something other
    than what this request was charged, so it must not be recorded as billed
    spend at any value -- including zero.
    """

    return bool(provider) and provider.strip().lower() in PER_REQUEST_BILLED_PROVIDERS


def is_external_priced_log_source(source: str | None) -> bool:
    return bool(source) and source.strip().lower() in EXTERNAL_PRICED_LOG_SOURCES


def external_priced_provider_for_log_source(source: str | None) -> str | None:
    if not source:
        return None
    return _LOG_SOURCE_PROVIDERS.get(source.strip().lower())
