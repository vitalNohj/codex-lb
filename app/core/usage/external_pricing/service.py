"""Cache-first external pricing for the request path.

The request path calls :func:`calculated_cost_for_request` and gets an answer from
persisted state alone. It never fetches a catalog, never scans one, never runs a
model search, never opens a browser, and never rewrites a record it already has.

A model id is looked up remotely in exactly two situations:

* it has never been seen for this provider, or
* its last lookup did not produce a price **and** its bounded retry deadline has
  passed.

Either way the request returns immediately; the lookup runs as a background job.
Concurrent first sightings of the same id collapse onto one in-flight job through
:class:`_LookupCoordinator`, so a burst of traffic to a new model produces one
catalog fetch, not one per request.

An unresolved model keeps whatever allow and quota behavior it had. Not knowing a
price is not a reason to refuse or to reprice a request.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

from app.core.usage.external_pricing.catalogs import (
    Catalog,
    CatalogFetchError,
    fetch_openrouter_catalog,
    is_external_priced_provider,
    order_catalogs,
)
from app.core.usage.external_pricing.resolution import (
    Resolution,
    ResolutionOutcome,
    resolve_model_price,
)
from app.core.usage.external_pricing.store import ExternalModelPriceStore, PriceRecord, normalize_lookup_key
from app.core.usage.pricing import UsageTokens, calculate_cost_from_usage
from app.db.models import ExternalPriceStatus
from app.db.session import get_background_session

logger = logging.getLogger(__name__)

# Ceiling on lookups running at once. Lookups are rare by construction, so this
# only bites when many previously unseen ids arrive together; it keeps that burst
# from becoming an unbounded fan-out of catalog fetches.
_MAX_CONCURRENT_LOOKUPS = 4

# How long one fetched pricing reference is reused across lookups. Long enough to
# collapse a burst of first sightings onto a single fetch, short enough that it is
# not a cache of record: the persisted store is.
_REFERENCE_CATALOG_MEMO_SECONDS = 60.0

# Supplies the serving integration's own catalog and routing configuration for a
# background lookup. Returning ``None`` for the catalog means the integration
# could not be consulted this time; resolution then falls back to the pricing
# reference alone rather than recording a wrong answer.
ServingContextLoader = Callable[[str], Awaitable["ServingContext | None"]]


@dataclass(frozen=True, slots=True)
class ServingContext:
    """What the serving integration contributes to one lookup.

    ``catalog`` is ``None`` in two situations that must not be confused.
    ``publishes_price_catalog=False`` means the integration has no rates to give by
    design (CLIProxyAPI proxies other vendors' models and publishes none), so the
    pricing reference is the whole answer and its verdict is authoritative. With
    ``publishes_price_catalog=True`` a ``None`` catalog means the listing could not
    be fetched or parsed this time, and callers must preserve prior values instead.
    """

    catalog: Catalog | None
    aliases: Mapping[str, str]
    prefixes: Sequence[tuple[str, bool]]
    publishes_price_catalog: bool = True

    @property
    def serving_catalog_missing(self) -> bool:
        """Whether a catalog that should have been available was not."""

        return self.publishes_price_catalog and self.catalog is None


@dataclass(frozen=True, slots=True)
class CalculatedCost:
    """A list-price cost computed from published rates and recorded usage."""

    cost_usd: float
    catalog_model: str
    catalog_source: str


class _LookupCoordinator:
    """Collapses concurrent lookups of the same key onto one job.

    Without this, the first burst of traffic to a newly routed model would start
    one catalog fetch per request. The in-flight map is keyed on
    ``(provider, incoming_model)`` and an entry is removed only after its task
    finishes, so a later request either joins the running job or starts the single
    next one.
    """

    def __init__(self, *, max_concurrent: int = _MAX_CONCURRENT_LOOKUPS) -> None:
        self._lock = asyncio.Lock()
        self._in_flight: dict[tuple[str, str], asyncio.Task[None]] = {}
        self._max_concurrent = max_concurrent

    async def submit(self, key: tuple[str, str], factory: Callable[[], Awaitable[None]]) -> None:
        async with self._lock:
            if key in self._in_flight:
                return
            if len(self._in_flight) >= self._max_concurrent:
                # A client enumerating models, or a routing-prefix change, can
                # present many unseen ids at once. Shedding the excess is safe and
                # bounded: nothing was persisted, so the next request for that id
                # schedules it again once the queue has drained.
                logger.debug(
                    "external price lookup deferred, %d already in flight provider=%s model=%s",
                    len(self._in_flight),
                    key[0],
                    key[1],
                )
                return
            task = asyncio.create_task(self._run(key, factory))
            self._in_flight[key] = task

    async def _run(self, key: tuple[str, str], factory: Callable[[], Awaitable[None]]) -> None:
        try:
            await factory()
        except asyncio.CancelledError:
            raise
        except Exception:
            # A lookup failure must never surface on the request that triggered
            # it. The record's retry state governs the next attempt.
            logger.warning("external price lookup failed provider=%s model=%s", key[0], key[1], exc_info=True)
        finally:
            async with self._lock:
                self._in_flight.pop(key, None)

    async def drain(self) -> None:
        """Await every in-flight lookup. Used by tests and by shutdown."""

        async with self._lock:
            tasks = list(self._in_flight.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


_coordinator = _LookupCoordinator()
_serving_context_loaders: dict[str, ServingContextLoader] = {}
_reference_catalog_memo: tuple[float, Catalog | None] | None = None
_reference_catalog_lock = asyncio.Lock()


def register_serving_context_loader(provider: str, loader: ServingContextLoader) -> None:
    """Register how a provider supplies its catalog and routing config.

    Registration inverts the dependency: ``core`` owns pricing, and each
    integration module declares how to reach its own catalog without core
    importing every sidecar.
    """

    _serving_context_loaders[provider.strip().lower()] = loader


def reset_serving_context_loaders() -> None:
    global _reference_catalog_memo
    _serving_context_loaders.clear()
    _reference_catalog_memo = None


def get_lookup_coordinator() -> _LookupCoordinator:
    return _coordinator


async def calculated_cost_for_request(
    *,
    provider: str,
    model: str,
    usage: UsageTokens | None,
    service_tier: str | None = None,
) -> tuple[CalculatedCost | None, ExternalPriceStatus | None]:
    """List-price cost for one request, plus the resolution status to record.

    Returns ``(None, None)`` for a provider that does not participate in external
    price resolution, so its request log keeps ``--`` with no unresolved marker.

    The status is returned even when a cost is not, because an eligible model that
    stays unresolved must be visibly distinguishable from a model that was never
    supposed to have a price.
    """

    if not is_external_priced_provider(provider):
        return None, None
    provider_key, model_key = normalize_lookup_key(provider, model)
    if not model_key:
        return None, None

    record = await _read_record(provider_key, model_key)

    if record is None or record.retry_due():
        # The request never waits on remote work; it reports what is known now.
        await _coordinator.submit(
            (provider_key, model_key),
            lambda: _run_lookup(provider_key, model_key, previous=record),
        )
        status = record.status if record is not None else ExternalPriceStatus.UNRESOLVED
        return None, status

    if not record.is_priced:
        return None, record.status

    if usage is None:
        # A priced model with no reported token usage has nothing to multiply.
        # That is missing usage, not an unresolved price, so it renders as ``--``.
        return None, record.status

    assert record.price is not None
    cost = calculate_cost_from_usage(usage, record.price, service_tier=service_tier)
    if cost is None:
        return None, record.status
    return (
        CalculatedCost(
            cost_usd=cost,
            catalog_model=record.catalog_model or record.incoming_model,
            catalog_source=record.catalog_source or "",
        ),
        record.status,
    )


async def _read_record(provider_key: str, model_key: str) -> PriceRecord | None:
    try:
        async with get_background_session() as session:
            return await ExternalModelPriceStore(session).get(provider_key, model_key)
    except Exception:
        # A store read failure must not fail the request or trigger a lookup
        # storm; the row is simply unavailable for this request.
        logger.warning("external price store read failed provider=%s model=%s", provider_key, model_key, exc_info=True)
        return None


async def _run_lookup(provider_key: str, model_key: str, *, previous: PriceRecord | None) -> None:
    """One bounded lookup for a single id, persisting whatever it concludes."""

    serving = await load_serving_context(provider_key)
    reference = await _load_reference_catalog()

    serving_catalog = serving.catalog if serving is not None else None
    if serving_catalog is None and reference is None:
        # Nothing could be consulted. Persisting an unresolved record here still
        # matters: it is what bounds retries so traffic cannot keep re-dispatching
        # this lookup while the catalogs are down.
        await _persist_unresolved(
            provider_key,
            model_key,
            status=ExternalPriceStatus.UNRESOLVED,
            detail="no catalog source was reachable",
            previous=previous,
        )
        return

    catalogs = order_catalogs(serving.catalog if serving is not None else None, reference)
    resolution = resolve_model_price(
        model_key,
        catalogs=catalogs,
        aliases=serving.aliases if serving is not None else None,
        prefixes=serving.prefixes if serving is not None else (),
    )
    await _persist_resolution(provider_key, model_key, resolution, previous=previous)


async def _persist_resolution(
    provider_key: str,
    model_key: str,
    resolution: Resolution,
    *,
    previous: PriceRecord | None,
) -> None:
    async with get_background_session() as session:
        store = ExternalModelPriceStore(session)
        if resolution.outcome is ResolutionOutcome.RESOLVED:
            assert resolution.price is not None
            assert resolution.catalog_model is not None
            assert resolution.catalog_source is not None
            await store.record_resolved(
                provider=provider_key,
                incoming_model=model_key,
                catalog_model=resolution.catalog_model,
                catalog_source=resolution.catalog_source,
                price=resolution.price,
                resolution_step=resolution.step or "exact",
            )
            return
        if resolution.outcome is ResolutionOutcome.NOT_TOKEN_PRICED:
            assert resolution.catalog_model is not None
            assert resolution.catalog_source is not None
            await store.record_not_token_priced(
                provider=provider_key,
                incoming_model=model_key,
                catalog_model=resolution.catalog_model,
                catalog_source=resolution.catalog_source,
                resolution_step=resolution.step or "exact",
                detail=resolution.detail or "not token priced",
            )
            return
        status = (
            ExternalPriceStatus.AMBIGUOUS
            if resolution.outcome is ResolutionOutcome.AMBIGUOUS
            else ExternalPriceStatus.UNRESOLVED
        )
        await store.record_unresolved(
            provider=provider_key,
            incoming_model=model_key,
            status=status,
            detail=resolution.detail,
            resolution_step=resolution.step,
            previous_attempts=previous.attempt_count if previous is not None else 0,
        )


async def _persist_unresolved(
    provider_key: str,
    model_key: str,
    *,
    status: ExternalPriceStatus,
    detail: str,
    previous: PriceRecord | None,
) -> None:
    async with get_background_session() as session:
        await ExternalModelPriceStore(session).record_unresolved(
            provider=provider_key,
            incoming_model=model_key,
            status=status,
            detail=detail,
            previous_attempts=previous.attempt_count if previous is not None else 0,
        )


async def load_serving_context(provider_key: str) -> ServingContext | None:
    """Serving catalog and routing config for ``provider_key``, or ``None``.

    ``None`` means the integration could not be consulted, which is distinct from
    it having nothing to say: callers must preserve prior values rather than treat
    it as an empty catalogue.
    """

    loader = _serving_context_loaders.get(provider_key)
    if loader is None:
        return None
    try:
        return await loader(provider_key)
    except Exception:
        logger.warning("serving catalog unavailable for provider=%s", provider_key, exc_info=True)
        return None


async def drain_pending_lookups() -> None:
    """Let every scheduled lookup finish. Called on shutdown and by tests."""

    await _coordinator.drain()


async def _load_reference_catalog() -> Catalog | None:
    """The pricing reference, memoised for a short window.

    Several previously unseen ids commonly appear together (a prefix change, a
    fresh deployment, a client enumerating models). Each one needs the same ~600
    entry catalog, so fetching it once for the burst keeps the cache-first
    semantics without the fan-out. The window is short enough that a maintenance
    pass or a later lookup still sees fresh rates.
    """

    global _reference_catalog_memo
    async with _reference_catalog_lock:
        memo = _reference_catalog_memo
        if memo is not None and (time.monotonic() - memo[0]) < _REFERENCE_CATALOG_MEMO_SECONDS:
            return memo[1]
        try:
            catalog: Catalog | None = await fetch_openrouter_catalog()
        except CatalogFetchError as exc:
            # OpenRouter is a pricing reference, not an availability authority: its
            # being unreachable removes a price source and nothing else. The
            # failure is memoised too, so a burst arriving during an outage does
            # not become a burst of failing fetches.
            logger.warning("OpenRouter pricing reference unavailable: %s", exc)
            catalog = None
        _reference_catalog_memo = (time.monotonic(), catalog)
        return catalog
