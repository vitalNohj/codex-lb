"""Cache-first external pricing for the request path.

The request path calls :func:`calculated_cost_for_request` and gets an answer from
persisted state alone. It never fetches a catalog, never scans one, never runs a
model search, never opens a browser, and never rewrites a record it already has.

A model id is looked up remotely in exactly two situations:

* it has never been seen for this provider, or
* its last lookup did not produce a price **and** its bounded retry deadline has
  passed.

Either way the request returns immediately; the lookup runs as a background job.
Concurrent first sightings collapse through a process-local coordinator and a
durable lookup lease, so replicas share one crash-recoverable job.

An unresolved model keeps whatever allow and quota behavior it had. Not knowing a
price is not a reason to refuse or to reprice a request.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.core.usage.external_pricing.catalogs import (
    Catalog,
    CatalogFetchError,
    OPENROUTER_REFERENCE_SOURCE,
    PROVIDER_OPENROUTER,
    fetch_openrouter_catalog,
    is_external_priced_provider,
    order_catalogs,
)
from app.core.usage.external_pricing.resolution import (
    Resolution,
    ResolutionOutcome,
    resolve_model_price,
)
from app.core.usage.external_pricing.store import (
    LOOKUP_WORK_TIMEOUT_SECONDS,
    ExternalModelPriceStore,
    PriceRecord,
    normalize_lookup_key,
)
from app.core.usage.pricing import UsageTokens, calculate_cost_from_usage
from app.db.models import ExternalPriceStatus
from app.db.session import get_background_session

logger = logging.getLogger(__name__)

# Outcomes that close the question: they are persisted without a retry deadline,
# so nothing on the request path revisits them.
_SETTLING_OUTCOMES = (ResolutionOutcome.RESOLVED, ResolutionOutcome.NOT_TOKEN_PRICED)

# Ceiling on lookups running at once. Lookups are rare by construction, so this
# only bites when many previously unseen ids arrive together; it keeps that burst
# from becoming an unbounded fan-out of catalog fetches.
_MAX_CONCURRENT_LOOKUPS = 4

# How long one fetched pricing reference is reused across lookups. Long enough to
# collapse a burst of first sightings onto a single fetch, short enough that it is
# not a cache of record: the persisted store is.
_REFERENCE_CATALOG_MEMO_SECONDS = 60.0
_STORAGE_FAILURE_COOLDOWN_SECONDS = 5.0

# Supplies the serving integration's own catalog and routing configuration for a
# background lookup. Returning ``None`` for the catalog means the integration
# could not be consulted this time; resolution then falls back to the pricing
# reference alone rather than recording a wrong answer.
ServingContextLoader = Callable[[str], Awaitable["ServingContext | None"]]


@dataclass(frozen=True, slots=True)
class ServingContext:
    """What the serving integration contributes to one lookup.

    ``catalog`` is ``None`` in three situations that must not be confused.
    ``publishes_price_catalog=False`` means the integration has no rates to give by
    design (CLIProxyAPI proxies other vendors' models and publishes none), so the
    pricing reference is the whole answer and its verdict is authoritative.
    ``integration_enabled=False`` means the operator switched the integration off,
    which is not a failure and not an answer -- nothing was asked. With both flags
    at their defaults a ``None`` catalog means the listing could not be fetched or
    parsed this time, and callers must preserve prior values instead.
    """

    catalog: Catalog | None
    aliases: Mapping[str, str]
    prefixes: Sequence[tuple[str, bool]]
    publishes_price_catalog: bool = True
    integration_enabled: bool = True

    @classmethod
    def disabled(
        cls,
        *,
        aliases: Mapping[str, str] | None = None,
        prefixes: Sequence[tuple[str, bool]] = (),
    ) -> "ServingContext":
        """The context of an integration the operator turned off.

        Distinct from a loader that raised: a switched-off integration has not
        failed to answer, so reporting it as an unavailable catalog would put a
        permanent failure line in front of an operator who did this on purpose.
        """

        return cls(
            catalog=None,
            aliases={} if aliases is None else aliases,
            prefixes=prefixes,
            publishes_price_catalog=False,
            integration_enabled=False,
        )

    @property
    def serving_catalog_missing(self) -> bool:
        """Whether a catalog that should have been available was not."""

        return self.integration_enabled and self.publishes_price_catalog and self.catalog is None


class CatalogAvailability(str, Enum):
    ANSWERED = "answered"
    UNAVAILABLE = "unavailable"
    TIMED_OUT = "timed_out"
    UNUSABLE = "unusable"
    DISABLED = "disabled"

    @property
    def authoritative(self) -> bool:
        return self is CatalogAvailability.ANSWERED


@dataclass(frozen=True, slots=True)
class SourceConsultations:
    serving: CatalogAvailability
    reference: CatalogAvailability

    def source_availability(self, source: str, provider_key: str) -> CatalogAvailability | None:
        if source == provider_key:
            return self.serving
        if source in (OPENROUTER_REFERENCE_SOURCE, PROVIDER_OPENROUTER):
            return self.reference
        return None

    def source_answered(self, source: str, provider_key: str) -> bool:
        availability = self.source_availability(source, provider_key)
        return availability is not None and availability.authoritative

    def with_unusable_resolution(self, resolution: Resolution, provider_key: str) -> "SourceConsultations":
        if resolution.outcome is not ResolutionOutcome.PRICE_UNPARSEABLE:
            return self
        source = resolution.catalog_source
        return SourceConsultations(
            serving=(CatalogAvailability.UNUSABLE if source == provider_key else self.serving),
            reference=(
                CatalogAvailability.UNUSABLE
                if source in (OPENROUTER_REFERENCE_SOURCE, PROVIDER_OPENROUTER) and source != provider_key
                else self.reference
            ),
        )


@dataclass(frozen=True, slots=True)
class CalculatedCost:
    """A list-price cost computed from published rates and recorded usage."""

    cost_usd: float
    catalog_model: str
    catalog_source: str


class _StorageResult(Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class _LookupCoordinator:
    """Collapses concurrent lookups of the same key within this process.

    Without this, the first burst of traffic to a newly routed model would start
    one catalog fetch per request. The in-flight map is keyed on
    ``(provider, incoming_model)`` and an entry is removed only after its task
    finishes. The store lease provides the equivalent guarantee across replicas.
    """

    def __init__(
        self,
        *,
        max_concurrent: int = _MAX_CONCURRENT_LOOKUPS,
        storage_failure_cooldown_seconds: float = _STORAGE_FAILURE_COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._lock = asyncio.Lock()
        self._in_flight: dict[tuple[str, str], asyncio.Task[None]] = {}
        self._max_concurrent = max_concurrent
        self._storage_failure_cooldown_seconds = storage_failure_cooldown_seconds
        self._storage_unavailable_until = 0.0
        self._clock = clock

    async def submit(self, key: tuple[str, str], factory: Callable[[], Awaitable[_StorageResult]]) -> None:
        async with self._lock:
            if self._clock() < self._storage_unavailable_until:
                return
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

    async def _run(self, key: tuple[str, str], factory: Callable[[], Awaitable[_StorageResult]]) -> None:
        storage_result: _StorageResult | None = None
        try:
            storage_result = await factory()
        except asyncio.CancelledError:
            raise
        except Exception:
            # A lookup failure must never surface on the request that triggered
            # it. The record's retry state governs the next attempt.
            logger.warning("external price lookup failed provider=%s model=%s", key[0], key[1], exc_info=True)
        finally:
            async with self._lock:
                if storage_result is _StorageResult.UNAVAILABLE:
                    self._storage_unavailable_until = self._clock() + self._storage_failure_cooldown_seconds
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
    schedule_lookup: bool = True,
) -> tuple[CalculatedCost | None, ExternalPriceStatus | None]:
    """List-price cost for one request, plus the resolution status to record.

    Returns ``(None, None)`` for a provider that does not participate in external
    price resolution, so its request log keeps ``--`` with no unresolved marker.

    The status is returned even when a cost is not, because an eligible model that
    stays unresolved must be visibly distinguishable from a model that was never
    supposed to have a price.

    ``schedule_lookup=False`` answers from persisted state without dispatching a
    background lookup. One request can ask this question twice -- once to settle a
    cost limit and once to write its log row -- and only one of those may own
    dispatch, or the second answer would depend on whether the first one's job
    happened to finish in between.
    """

    if not is_external_priced_provider(provider):
        return None, None
    provider_key, model_key = normalize_lookup_key(provider, model)
    if not model_key:
        return None, None

    record = await _read_record(provider_key, model_key)
    if record is _StorageResult.UNAVAILABLE:
        return None, ExternalPriceStatus.PENDING

    retryable_status = record is not None and record.status in (
        ExternalPriceStatus.PENDING,
        ExternalPriceStatus.UNRESOLVED,
        ExternalPriceStatus.AMBIGUOUS,
    )
    if record is None or (retryable_status and record.retry_due()):
        # The request never waits on remote work; it reports what is known now.
        if schedule_lookup:
            await _coordinator.submit(
                (provider_key, model_key),
                lambda: _run_lookup(provider_key, model_key),
            )
        if record is None:
            # First sighting. No lookup has concluded anything yet, so this row
            # is pending rather than unresolved: an eligible model is only worth
            # marking once a lookup has actually failed to price it.
            return None, ExternalPriceStatus.PENDING
        if not record.is_priced:
            return None, record.status
        # A rate preserved through an unreadable upstream price still serves.
    elif not record.is_priced:
        return None, record.status

    if usage is None:
        # A priced model with no reported token usage has nothing to multiply.
        # That is missing usage, not an unresolved price, so it renders as ``--``.
        return None, record.status

    usage_components = (usage.input_tokens, usage.output_tokens, usage.cached_input_tokens)
    if any(not math.isfinite(component) or component < 0 for component in usage_components):
        return None, record.status

    assert record.price is not None
    cost = calculate_cost_from_usage(usage, record.price, service_tier=service_tier)
    if cost is None or not math.isfinite(cost) or cost < 0:
        return None, record.status
    return (
        CalculatedCost(
            cost_usd=cost,
            catalog_model=record.catalog_model or record.incoming_model,
            catalog_source=record.catalog_source or "",
        ),
        record.status,
    )


async def _read_record(provider_key: str, model_key: str) -> PriceRecord | None | _StorageResult:
    try:
        async with get_background_session() as session:
            return await ExternalModelPriceStore(session).get(provider_key, model_key)
    except Exception:
        # A failed read is unknown durable state, not evidence of a first
        # sighting. Requests remain available and unpriced without scheduling
        # remote work that cannot acquire or update its durable claim.
        logger.warning("external price store read failed provider=%s model=%s", provider_key, model_key, exc_info=True)
        return _StorageResult.UNAVAILABLE


def source_consultations(
    serving: ServingContext | None,
    *,
    reference_available: bool,
) -> SourceConsultations:
    if serving is not None and not serving.integration_enabled:
        serving_availability = CatalogAvailability.DISABLED
    elif serving is None or serving.serving_catalog_missing:
        serving_availability = CatalogAvailability.UNAVAILABLE
    else:
        serving_availability = CatalogAvailability.ANSWERED
    return SourceConsultations(
        serving=serving_availability,
        reference=(CatalogAvailability.ANSWERED if reference_available else CatalogAvailability.UNAVAILABLE),
    )


def preservation_reason(
    record: PriceRecord | None,
    provider_key: str,
    resolution: Resolution,
    *,
    consultations: SourceConsultations,
) -> str | None:
    consultations = consultations.with_unusable_resolution(resolution, provider_key)
    if resolution.outcome is ResolutionOutcome.PRICE_UNPARSEABLE:
        return "catalog price could not be parsed authoritatively"
    owner = record.catalog_source if record is not None else None
    if record is not None and record.is_priced:
        if resolution.outcome is not ResolutionOutcome.RESOLVED:
            return "stored price has no valid replacement"
        if owner is not None and resolution.catalog_source != owner:
            return f"stored price remains owned by {owner}"
    if (
        record is not None
        and record.is_settled
        and owner is not None
        and not consultations.source_answered(owner, provider_key)
    ):
        return f"owning source {owner} did not provide an authoritative answer"
    if (
        owner is None
        and record is not None
        and record.is_settled
        and resolution.outcome not in _SETTLING_OUTCOMES
        and not (
            consultations.source_answered(provider_key, provider_key)
            and consultations.source_answered(OPENROUTER_REFERENCE_SOURCE, provider_key)
        )
    ):
        return "an ownerless settled record cannot be weakened without complete source answers"
    if (
        resolution.outcome in _SETTLING_OUTCOMES
        and resolution.catalog_source != provider_key
        and owner != resolution.catalog_source
        and not consultations.source_answered(provider_key, provider_key)
    ):
        return f"serving source {provider_key} did not provide an authoritative answer"
    return None


async def _run_lookup(provider_key: str, model_key: str) -> _StorageResult:
    """One bounded lookup for a single id, persisting whatever it concludes."""

    try:
        async with get_background_session() as session:
            claim = await ExternalModelPriceStore(session).claim_lookup(provider_key, model_key)
    except Exception:
        logger.warning("external price store claim failed provider=%s model=%s", provider_key, model_key, exc_info=True)
        return _StorageResult.UNAVAILABLE
    if claim is None:
        return _StorageResult.AVAILABLE
    previous = claim.record

    try:
        async with asyncio.timeout(LOOKUP_WORK_TIMEOUT_SECONDS):
            serving = await load_serving_context(provider_key)
            reference = await _load_reference_catalog()
    except TimeoutError:
        await preserve_record_for_retry(
            provider_key,
            model_key,
            record=previous,
            detail="catalog lookup timed out",
            claim_token=claim.token,
        )
        return _StorageResult.AVAILABLE

    serving_catalog = serving.catalog if serving is not None else None
    catalogs = order_catalogs(serving_catalog, reference)
    resolution = resolve_model_price(
        model_key,
        catalogs=catalogs,
        aliases=serving.aliases if serving is not None else None,
        prefixes=serving.prefixes if serving is not None else (),
    )

    reason = preservation_reason(
        previous,
        provider_key,
        resolution,
        consultations=source_consultations(serving, reference_available=reference is not None),
    )
    if reason is not None:
        await preserve_record_for_retry(
            provider_key,
            model_key,
            record=previous,
            detail=reason,
            resolution=resolution,
            claim_token=claim.token,
        )
        return _StorageResult.AVAILABLE

    await _persist_resolution(
        provider_key,
        model_key,
        resolution,
        previous=previous,
        claim_token=claim.token,
    )
    return _StorageResult.AVAILABLE


async def _persist_resolution(
    provider_key: str,
    model_key: str,
    resolution: Resolution,
    *,
    previous: PriceRecord | None,
    claim_token: str,
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
                claim_token=claim_token,
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
                claim_token=claim_token,
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
            claim_token=claim_token,
        )


async def preserve_record_for_retry(
    provider_key: str,
    model_key: str,
    *,
    record: PriceRecord | None,
    detail: str,
    resolution: Resolution | None = None,
    claim_token: str | None = None,
    expected_updated_at: datetime | None = None,
) -> bool:
    async with get_background_session() as session:
        return await ExternalModelPriceStore(session).record_retryable_failure(
            provider=provider_key,
            incoming_model=model_key,
            record=record,
            detail=detail,
            catalog_model=(
                resolution.catalog_model
                if resolution is not None and resolution.outcome is ResolutionOutcome.PRICE_UNPARSEABLE
                else None
            ),
            catalog_source=(
                resolution.catalog_source
                if resolution is not None and resolution.outcome is ResolutionOutcome.PRICE_UNPARSEABLE
                else None
            ),
            previous_attempts=record.attempt_count if record is not None else 0,
            claim_token=claim_token,
            expected_updated_at=expected_updated_at,
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
