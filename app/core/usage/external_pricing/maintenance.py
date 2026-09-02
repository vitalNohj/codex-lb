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
from dataclasses import dataclass, field

from app.core.usage.external_pricing.catalogs import (
    Catalog,
    CatalogFetchError,
    fetch_openrouter_catalog,
)
from app.core.usage.external_pricing.resolution import ResolutionOutcome, resolve_model_price
from app.core.usage.external_pricing.service import (
    CatalogAvailability,
    ServingContext,
    SourceConsultations,
    load_serving_context,
    preservation_reason,
    preserve_record_for_retry,
)
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
    preserved_while_disabled: int = 0
    preserved_without_replacement: list[RecordChange] = field(default_factory=list)
    preserved_unparseable: list[RecordChange] = field(default_factory=list)
    became_not_token_priced: list[RecordChange] = field(default_factory=list)
    unresolved: list[RecordChange] = field(default_factory=list)
    ambiguous: list[RecordChange] = field(default_factory=list)
    catalog_failures: list[str] = field(default_factory=list)
    disabled_integrations: list[str] = field(default_factory=list)
    skipped_disabled: int = 0

    def render(self) -> str:
        lines = [
            "External model price maintenance",
            f"- Records examined: {self.examined}",
            f"- Rates updated: {len(self.updated)}",
            f"- Newly resolved: {len(self.newly_resolved)}",
            f"- Unchanged: {self.unchanged}",
            f"- Now listed without a per-token price: {len(self.became_not_token_priced)}",
            f"- Preserved after a source failure: {self.preserved_on_failure}",
            f"- Preserved while an integration is disabled: {self.preserved_while_disabled}",
            f"- Preserved without a valid replacement: {len(self.preserved_without_replacement)}",
            f"- Preserved after an unreadable published price: {len(self.preserved_unparseable)}",
            f"- Skipped, integration disabled: {self.skipped_disabled}",
            f"- Still unresolved: {len(self.unresolved)}",
            f"- Ambiguous: {len(self.ambiguous)}",
        ]
        for label, changes in (
            ("Updated", self.updated),
            ("Newly resolved", self.newly_resolved),
            ("Now listed without a per-token price", self.became_not_token_priced),
            ("Preserved without a valid replacement", self.preserved_without_replacement),
            ("Preserved after an unreadable published price", self.preserved_unparseable),
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
        if self.disabled_integrations:
            lines.append("")
            # A disabled integration was not consulted, so its own records are
            # preserved rather than left "untouched" by accident -- but records it
            # never owned are still judged against the pricing reference. Saying
            # both is what keeps the section honest about what the pass did.
            lines.append("Integrations disabled (not consulted; their own rates preserved):")
            lines.extend(f"  {provider}" for provider in self.disabled_integrations)
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
    unavailable_providers: set[str] = set()
    disabled_providers: set[str] = set()
    for provider in providers:
        context = await load_serving_context(provider)
        contexts[provider] = context
        if context is not None and not context.integration_enabled:
            # The operator switched this integration off. Nothing was asked of it,
            # so it has neither failed nor answered; its records are left exactly
            # as they are and the report says why.
            disabled_providers.add(provider)
            report.disabled_integrations.append(provider)
            continue
        # An integration that publishes no price catalog by design contributes
        # nothing here and has not failed.
        if context is None or context.serving_catalog_missing:
            unavailable_providers.add(provider)
            report.catalog_failures.append(f"{provider}: serving catalog unavailable")

    reference_unavailable = reference_error is not None
    for record in records:
        disabled = record.provider in disabled_providers
        context = contexts.get(record.provider)
        serving_catalog = context.catalog if context is not None else None
        serving_failed = record.provider in unavailable_providers
        await _refresh_record(
            record,
            serving=serving_catalog,
            serving_disabled=disabled,
            serving_failed=serving_failed,
            reference=reference,
            reference_unavailable=reference_unavailable,
            context=context,
            report=report,
        )

    return report


async def _fetch_reference() -> tuple[Catalog | None, str | None]:
    try:
        return await fetch_openrouter_catalog(), None
    except CatalogFetchError as exc:
        return None, f"openrouter: {exc}"


def _count_preserved(report: MaintenanceReport, *, disabled: bool) -> None:
    """Record one preserved record under the reason it was preserved for."""

    if disabled:
        report.preserved_while_disabled += 1
    else:
        report.preserved_on_failure += 1


async def _refresh_record(
    record: PriceRecord,
    *,
    serving: Catalog | None,
    serving_disabled: bool,
    serving_failed: bool,
    reference: Catalog | None,
    reference_unavailable: bool,
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

    consultations = SourceConsultations(
        serving=(
            CatalogAvailability.DISABLED
            if serving_disabled
            else CatalogAvailability.UNAVAILABLE
            if serving_failed
            else CatalogAvailability.ANSWERED
        ),
        reference=(CatalogAvailability.UNAVAILABLE if reference_unavailable else CatalogAvailability.ANSWERED),
    )
    reason = preservation_reason(
        record,
        record.provider,
        resolution,
        consultations=consultations,
    )
    if reason is not None:
        if record.is_settled:
            applied = True
        else:
            applied = await preserve_record_for_retry(
                record.provider,
                record.incoming_model,
                record=record,
                detail=reason,
                resolution=resolution,
                expected_updated_at=record.updated_at,
            )
            if not applied:
                return
        if resolution.outcome is ResolutionOutcome.PRICE_UNPARSEABLE:
            report.preserved_unparseable.append(
                RecordChange(
                    provider=record.provider,
                    incoming_model=record.incoming_model,
                    description=resolution.detail or "catalog price could not be parsed",
                )
            )
        else:
            owner = record.catalog_source
            source_unavailable = (owner is not None and not consultations.source_answered(owner, record.provider)) or (
                owner is None and (serving_failed or reference_unavailable)
            )
            if source_unavailable:
                _count_preserved(report, disabled=serving_disabled)
                if serving_disabled and reference is None:
                    report.skipped_disabled += 1
            else:
                report.preserved_without_replacement.append(
                    RecordChange(
                        provider=record.provider,
                        incoming_model=record.incoming_model,
                        description=reason,
                    )
                )
        return

    async with get_background_session() as session:
        store = ExternalModelPriceStore(session)
        if resolution.outcome is ResolutionOutcome.RESOLVED:
            assert resolution.price is not None
            assert resolution.catalog_model is not None
            assert resolution.catalog_source is not None
            changed = _rates_changed(record, resolution.price.input_per_1m, resolution.price.output_per_1m)
            was_priced = record.is_priced
            applied = await store.record_resolved(
                provider=record.provider,
                incoming_model=record.incoming_model,
                catalog_model=resolution.catalog_model,
                catalog_source=resolution.catalog_source,
                price=resolution.price,
                resolution_step=resolution.step or "exact",
                expected_updated_at=record.updated_at,
            )
            if not applied:
                return
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
            applied = await store.record_not_token_priced(
                provider=record.provider,
                incoming_model=record.incoming_model,
                catalog_model=resolution.catalog_model,
                catalog_source=resolution.catalog_source,
                resolution_step=resolution.step or "exact",
                detail=resolution.detail or "not token priced",
                expected_updated_at=record.updated_at,
            )
            if not applied:
                return
            if record.status is ExternalPriceStatus.NOT_TOKEN_PRICED:
                report.unchanged += 1
            else:
                report.became_not_token_priced.append(
                    RecordChange(
                        provider=record.provider,
                        incoming_model=record.incoming_model,
                        description=(
                            f"{resolution.catalog_source}:{resolution.catalog_model} "
                            "is listed without a per-token price"
                        ),
                    )
                )
            return

        status = (
            ExternalPriceStatus.AMBIGUOUS
            if resolution.outcome is ResolutionOutcome.AMBIGUOUS
            else ExternalPriceStatus.UNRESOLVED
        )
        applied = await store.record_unresolved(
            provider=record.provider,
            incoming_model=record.incoming_model,
            status=status,
            detail=resolution.detail,
            resolution_step=resolution.step,
            previous_attempts=record.attempt_count,
            expected_updated_at=record.updated_at,
        )
        if not applied:
            return
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
