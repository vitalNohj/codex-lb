"""Catalog sources for external-integration price resolution.

Each source is an authoritative structured endpoint published by the party that
sets the price. A published input/output token rate multiplied by the recorded
token usage is a calculated list price -- deterministic arithmetic, not an
estimate -- and is kept separate from any amount the upstream reported as billed.

Two roles, deliberately distinct:

*serving catalog*
    The catalog of the integration that actually served the request. It is asked
    first because a shared id can carry different prices on different services:
    ``deepseek/deepseek-chat`` is listed by both OrcaRouter and OpenRouter, and 37
    of the 98 shared ids are priced differently.

*pricing reference*
    OpenRouter's structured catalog, consulted as the broad fallback for ids the
    serving catalog does not price. It is a **pricing** reference only. Absence
    from OpenRouter says nothing about whether a model exists, was added, or was
    removed; serving integrations own discovery and routing state, and nothing
    here may feed back into them.

Fetching happens off the request path. Every fetcher raises on transport, HTTP,
or shape failure so a caller can tell a real absence from an unreachable source
and preserve prior values instead of overwriting them with nothing.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from enum import Enum
from typing import cast

import aiohttp

from app.core.clients.http import lease_http_session
from app.core.types import JsonValue
from app.core.usage.external_pricing.providers import (
    EXTERNAL_PRICED_PROVIDERS,
    PROVIDER_CLIPROXY,
    PROVIDER_OPENROUTER,
    PROVIDER_ORCAROUTER,
    is_external_priced_provider,
)
from app.core.usage.external_pricing.resolution import Catalog, CatalogEntry, UnpricedReason
from app.core.usage.pricing import ModelPrice
from app.core.utils.json_guards import is_json_mapping

logger = logging.getLogger(__name__)

__all__ = [
    "EXTERNAL_PRICED_PROVIDERS",
    "PROVIDER_CLIPROXY",
    "PROVIDER_OPENROUTER",
    "PROVIDER_ORCAROUTER",
    "Catalog",
    "CatalogEntry",
    "CatalogFetchError",
    "catalog_from_sidecar_models",
    "fetch_openrouter_catalog",
    "is_external_priced_provider",
    "order_catalogs",
    "parse_openai_style_catalog",
    "parse_per_token_pricing",
]

# Broad pricing reference. Public, unauthenticated, and structured.
OPENROUTER_CATALOG_URL = "https://openrouter.ai/api/v1/models"

_PER_TOKEN_TO_PER_1M = 1_000_000.0
_FETCH_TIMEOUT_SECONDS = 20.0


class CatalogFetchError(RuntimeError):
    """A catalog could not be fetched or parsed.

    Distinct from "the catalog does not list this model". A caller that sees this
    must preserve whatever it already had rather than recording an absence.
    """


async def fetch_openrouter_catalog(*, url: str = OPENROUTER_CATALOG_URL) -> Catalog:
    """Fetch OpenRouter's structured catalog as the broad pricing reference."""

    payload = await _fetch_json(url, source="openrouter")
    return parse_openai_style_catalog(payload, source=PROVIDER_OPENROUTER)


def parse_openai_style_catalog(payload: JsonValue, *, source: str) -> Catalog:
    """Parse an OpenAI-shaped ``{"data": [{"id", "pricing"}]}`` catalog.

    OpenRouter and OrcaRouter both publish this shape with per-token decimal
    string prices. An entry that lists a model without per-token rates (per-request
    image models, per-minute audio, routers) is kept with ``price=None``: the
    listing is real and must not be retried as a fetch failure.

    An entry that *does* carry a ``pricing`` block this parser could not read is
    kept as ``UNPARSEABLE`` instead. That is not the same fact: an upstream schema
    change would otherwise settle every model as "not token priced", clear its
    rate, and set no retry.
    """

    if not is_json_mapping(payload):
        raise CatalogFetchError(f"{source} catalog response was not a JSON object")
    raw_models = payload.get("data")
    if not isinstance(raw_models, list):
        raise CatalogFetchError(f"{source} catalog response has no 'data' list")
    entries: list[CatalogEntry] = []
    for raw in raw_models:
        if not is_json_mapping(raw):
            continue
        model_id = raw.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        raw_pricing = raw.get("pricing")
        price = parse_per_token_pricing(raw_pricing)
        entries.append(
            CatalogEntry(
                model_id=model_id.strip(),
                price=price,
                unpriced_reason=_unpriced_reason(price, raw_pricing),
            )
        )
    if not entries:
        raise CatalogFetchError(f"{source} catalog listed no usable models")
    return Catalog.from_entries(source, entries)


class _RateReading(Enum):
    """What one published rate field says.

    The distinction is between the catalog answering and this build failing.
    ``DECLARED_NONE`` is an answer: catalogs say "no per-token rate" by publishing
    a negative sentinel (``"-1"`` on ``openrouter/auto``), an explicit ``null``, or
    an empty string. ``UNREADABLE`` is a shape this build cannot interpret -- a
    nested object, a renamed unit field, a non-numeric string -- which is a parse
    failure and must never settle the question.
    """

    MISSING = "missing"
    DECLARED_NONE = "declared_none"
    PARSED = "parsed"
    UNREADABLE = "unreadable"


def _read_rate(value: JsonValue) -> tuple[_RateReading, float | None]:
    if value is None:
        return _RateReading.DECLARED_NONE, None
    if isinstance(value, bool):
        return _RateReading.UNREADABLE, None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return _RateReading.DECLARED_NONE, None
        try:
            number = float(stripped)
        except ValueError:
            return _RateReading.UNREADABLE, None
    else:
        return _RateReading.UNREADABLE, None
    if number < 0:
        return _RateReading.DECLARED_NONE, None
    return _RateReading.PARSED, number


def _read_rate_field(raw_pricing: dict[str, JsonValue], key: str) -> _RateReading:
    if key not in raw_pricing:
        return _RateReading.MISSING
    return _read_rate(raw_pricing[key])[0]


def _unpriced_reason(price: ModelPrice | None, raw_pricing: JsonValue) -> UnpricedReason:
    """Whether an unpriced entry declares no token rate or carries unreadable ones.

    Keyed on the published *values*, not on which keys exist. A catalog that omits
    ``prompt``/``completion``, or publishes them as a negative sentinel, ``null``,
    or an empty string, has said the model is not token priced -- a settled answer
    that carries no retry state. Only a shape this build genuinely could not read,
    or a half-published pair it cannot turn into a price, leaves the question open
    so the prior rate stands and the source is re-read.
    """

    if price is not None:
        return UnpricedReason.NO_TOKEN_RATE
    if not is_json_mapping(raw_pricing):
        return UnpricedReason.NO_TOKEN_RATE
    readings = [_read_rate_field(raw_pricing, key) for key in ("prompt", "completion")]
    if _RateReading.UNREADABLE in readings:
        return UnpricedReason.UNPARSEABLE
    if _RateReading.DECLARED_NONE in readings:
        # The catalog published the field and used it to say there is no rate.
        # That is its answer, and half a declared rate still cannot be multiplied
        # by tokens, so the model is not token priced.
        return UnpricedReason.NO_TOKEN_RATE
    # A readable rate whose counterpart key is absent entirely is the shape a
    # renamed or restructured schema produces. Nothing is settled by it.
    if _RateReading.PARSED in readings:
        return UnpricedReason.UNPARSEABLE
    return UnpricedReason.NO_TOKEN_RATE


def parse_per_token_pricing(pricing: JsonValue) -> ModelPrice | None:
    """Parse per-token USD rates into per-1M rates, or ``None`` when absent.

    ``cached_input_per_1m`` is intentionally left unset so cached input prices at
    the full input rate. The catalogs do not publish a cache-read rate for every
    model, and assuming an undocumented discount would substitute an invented
    number for a published one.
    """

    if not is_json_mapping(pricing):
        return None
    input_per_1m = _parse_per_token_usd(pricing.get("prompt"))
    output_per_1m = _parse_per_token_usd(pricing.get("completion"))
    if input_per_1m is None or output_per_1m is None:
        return None
    return ModelPrice(input_per_1m=input_per_1m, output_per_1m=output_per_1m)


def _parse_per_token_usd(value: JsonValue) -> float | None:
    reading, per_token = _read_rate(value)
    if reading is not _RateReading.PARSED or per_token is None:
        return None
    return per_token * _PER_TOKEN_TO_PER_1M


def catalog_from_sidecar_models(
    source: str,
    models: Sequence[tuple[str, ModelPrice | None, JsonValue]],
) -> Catalog:
    """Build a catalog from an already-fetched sidecar ``/models`` listing.

    Reuses the listing the serving integration fetched for routing, so resolving a
    price costs no additional upstream call in the common case. The raw ``pricing``
    payload travels with each entry so an id the sidecar listed with unreadable
    rate fields is not mistaken for one it listed with no rates at all.
    """

    return Catalog.from_entries(
        source,
        (
            CatalogEntry(
                model_id=model_id,
                price=price,
                unpriced_reason=_unpriced_reason(price, raw_pricing),
            )
            for model_id, price, raw_pricing in models
        ),
    )


async def _fetch_json(url: str, *, source: str) -> JsonValue:
    timeout = aiohttp.ClientTimeout(total=_FETCH_TIMEOUT_SECONDS, connect=_FETCH_TIMEOUT_SECONDS)
    headers = {
        "Accept": "application/json",
        "User-Agent": "codex-lb/external-pricing",
    }
    try:
        async with lease_http_session() as session:
            async with session.get(url, headers=headers, timeout=timeout) as response:
                text = await response.text()
                if response.status >= 400:
                    raise CatalogFetchError(f"{source} catalog returned HTTP {response.status}")
    except CatalogFetchError:
        raise
    except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
        raise CatalogFetchError(f"failed to fetch {source} catalog: {exc}") from exc
    if not text:
        raise CatalogFetchError(f"{source} catalog returned an empty body")
    try:
        return cast(JsonValue, json.loads(text))
    except json.JSONDecodeError as exc:
        raise CatalogFetchError(f"{source} catalog returned invalid JSON: {exc}") from exc


def order_catalogs(serving: Catalog | None, reference: Catalog | None) -> list[Catalog]:
    """Serving catalog first, pricing reference second, skipping absent ones."""

    ordered: list[Catalog] = []
    for catalog in (serving, reference):
        if catalog is not None:
            ordered.append(catalog)
    return ordered
