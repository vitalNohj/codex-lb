"""One explicit refresh pass over persisted external price records.

Deliberately not scheduled. Prices change rarely, a background poller would spend
every interval re-confirming the same numbers, and an unattended refresh that
silently swaps a rate is harder to reason about than an operator-run pass whose
output says exactly what changed.

The pass is idempotent: running it twice against an unchanged catalog produces the
same rows and reports zero changes. It fetches each catalog once in bulk rather
than per record, and a source it cannot fetch or parse leaves every record that
depended on it untouched -- preserving a known rate is strictly better than
replacing it with nothing because a request timed out.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.core.usage.external_pricing.catalogs import (
    Catalog,
    CatalogFetchError,
    fetch_openrouter_catalog,
)
from app.core.usage.external_pricing.resolution import ResolutionOutcome, resolve_model_price
from app.core.usage.external_pricing.service import ServingContext, load_serving_context
from app.core.usage.external_pricing.store import ExternalModelPriceStore, PriceRecord
from app.db.models import ExternalPriceStatus
from app.db.session import get_background_session

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RecordChange:
    provider: str
    incoming_model: str
    description: str


@dataclass(slots=True)
class MaintenanceReport:
    """What one pass did, in a shape an operator can act on."""

    examined: int = 0
    updated: list[RecordChange] = field(default_factory=list)
    newly_resolved: list[RecordChange] = field(default_factory=list)
    unchanged: int = 0
    preserved_on_failure: int = 0
    unresolved: list[RecordChange] = field(default_factory=list)
    ambiguous: list[RecordChange] = field(default_factory=list)
    catalog_failures: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            "External model price maintenance",
            f"- Records examined: {self.examined}",
            f"- Rates updated: {len(self.updated)}",
            f"- Newly resolved: {len(self.newly_resolved)}",
            f"- Unchanged: {self.unchanged}",
            f"- Preserved after a source failure: {self.preserved_on_failure}",
            f"- Still unresolved: {len(self.unresolved)}",
            f"- Ambiguous: {len(self.ambiguous)}",
        ]
        for label, changes in (
            ("Updated", self.updated),
            ("Newly resolved", self.newly_resolved),
            ("Unresolved", self.unresolved),
            ("Ambiguous", self.ambiguous),
        ):
            if not changes:
                continue
            lines.append("")
            lines.append(f"{label}:")
            lines.extend(f"  {change.provider}/{change.incoming_model}: {change.description}" for change in changes)
        if self.catalog_failures:
            lines.append("")
            lines.append("Catalog sources unavailable (prior values preserved):")
            lines.extend(f"  {failure}" for failure in self.catalog_failures)
        return "\n".join(lines)


async def run_maintenance_pass() -> MaintenanceReport:
    """Refresh every persisted record once against freshly fetched catalogs."""

    report = MaintenanceReport()

    async with get_background_session() as session:
        records = await ExternalModelPriceStore(session).list_all()
    report.examined = len(records)
    if not records:
        return report

    reference, reference_error = await _fetch_reference()
    if reference_error is not None:
        report.catalog_failures.append(reference_error)

    providers = sorted({record.provider for record in records})
    contexts: dict[str, ServingContext | None] = {}
    for provider in providers:
        context = await load_serving_context(provider)
        contexts[provider] = context
        if context is None or context.catalog is None:
            report.catalog_failures.append(f"{provider}: serving catalog unavailable")

    for record in records:
        context = contexts.get(record.provider)
        serving_catalog = context.catalog if context is not None else None
        if serving_catalog is None and reference is None:
            # Every source this record could have used is unavailable. Leaving the
            # row exactly as it is preserves a rate that is probably still correct.
            report.preserved_on_failure += 1
            continue
        await _refresh_record(
            record,
            serving=serving_catalog,
            reference=reference,
            context=context,
            report=report,
        )

    return report


async def _fetch_reference() -> tuple[Catalog | None, str | None]:
    try:
        return await fetch_openrouter_catalog(), None
    except CatalogFetchError as exc:
        return None, f"openrouter: {exc}"


async def _refresh_record(
    record: PriceRecord,
    *,
    serving: Catalog | None,
    reference: Catalog | None,
    context: ServingContext | None,
    report: MaintenanceReport,
) -> None:
    catalogs = [catalog for catalog in (serving, reference) if catalog is not None]
    resolution = resolve_model_price(
        record.incoming_model,
        catalogs=catalogs,
        aliases=context.aliases if context is not None else None,
        prefixes=context.prefixes if context is not None else (),
    )

    if resolution.outcome is ResolutionOutcome.UNRESOLVED and record.is_priced and serving is None:
        # The record's own catalog was unreachable and the reference alone did not
        # recognise the id. That is a fetch gap, not a delisting, so the known rate
        # stays.
        report.preserved_on_failure += 1
        return

    async with get_background_session() as session:
        store = ExternalModelPriceStore(session)
        if resolution.outcome is ResolutionOutcome.RESOLVED:
            assert resolution.price is not None
            assert resolution.catalog_model is not None
            assert resolution.catalog_source is not None
            changed = _rates_changed(record, resolution.price.input_per_1m, resolution.price.output_per_1m)
            was_priced = record.is_priced
            await store.record_resolved(
                provider=record.provider,
                incoming_model=record.incoming_model,
                catalog_model=resolution.catalog_model,
                catalog_source=resolution.catalog_source,
                price=resolution.price,
                resolution_step=resolution.step or "exact",
            )
            change = RecordChange(
                provider=record.provider,
                incoming_model=record.incoming_model,
                description=(
                    f"{resolution.catalog_source}:{resolution.catalog_model} "
                    f"in={resolution.price.input_per_1m} out={resolution.price.output_per_1m}"
                ),
            )
            if not was_priced:
                report.newly_resolved.append(change)
            elif changed:
                report.updated.append(change)
            else:
                report.unchanged += 1
            return

        if resolution.outcome is ResolutionOutcome.NOT_TOKEN_PRICED:
            assert resolution.catalog_model is not None
            assert resolution.catalog_source is not None
            await store.record_not_token_priced(
                provider=record.provider,
                incoming_model=record.incoming_model,
                catalog_model=resolution.catalog_model,
                catalog_source=resolution.catalog_source,
                resolution_step=resolution.step or "exact",
                detail=resolution.detail or "not token priced",
            )
            report.unchanged += 1
            return

        status = (
            ExternalPriceStatus.AMBIGUOUS
            if resolution.outcome is ResolutionOutcome.AMBIGUOUS
            else ExternalPriceStatus.UNRESOLVED
        )
        await store.record_unresolved(
            provider=record.provider,
            incoming_model=record.incoming_model,
            status=status,
            detail=resolution.detail,
            resolution_step=resolution.step,
            previous_attempts=record.attempt_count,
        )
        change = RecordChange(
            provider=record.provider,
            incoming_model=record.incoming_model,
            description=resolution.detail or "no catalog entry",
        )
        if status is ExternalPriceStatus.AMBIGUOUS:
            report.ambiguous.append(change)
        else:
            report.unresolved.append(change)


def _rates_changed(record: PriceRecord, input_per_1m: float, output_per_1m: float) -> bool:
    if record.price is None:
        return True
    return record.price.input_per_1m != input_per_1m or record.price.output_per_1m != output_per_1m


def summarize_by_status(records: Sequence[PriceRecord]) -> Mapping[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.status.value] = counts.get(record.status.value, 0) + 1
    return counts
