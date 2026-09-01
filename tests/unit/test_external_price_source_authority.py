from __future__ import annotations

from datetime import UTC, datetime
from itertools import product

import pytest

from app.core.usage.external_pricing.resolution import Resolution, ResolutionOutcome
from app.core.usage.external_pricing.service import (
    CatalogAvailability,
    SourceConsultations,
    preservation_reason,
)
from app.core.usage.external_pricing.store import PriceRecord
from app.core.usage.pricing import ModelPrice
from app.db.models import ExternalPriceStatus

pytestmark = pytest.mark.unit

_SERVING = "orcarouter"
_REFERENCE = "openrouter"
_NOW = datetime(2026, 8, 31, tzinfo=UTC)


def _record(state: str, owner: str | None) -> PriceRecord:
    statuses = {
        "resolved": ExternalPriceStatus.RESOLVED,
        "unresolved": ExternalPriceStatus.UNRESOLVED,
        "ambiguous": ExternalPriceStatus.AMBIGUOUS,
        "not_token_priced": ExternalPriceStatus.NOT_TOKEN_PRICED,
        "unparseable": ExternalPriceStatus.UNRESOLVED,
    }
    price = ModelPrice(2.0, 4.0) if state == "resolved" else None
    return PriceRecord(
        provider=_SERVING,
        incoming_model="vendor/model-x",
        status=statuses[state],
        catalog_model="vendor/model-x" if owner is not None else None,
        catalog_source=owner,
        price=price,
        resolution_step="exact" if owner is not None else None,
        detail="catalog price could not be parsed" if state == "unparseable" else None,
        retrieved_at=_NOW,
        updated_at=_NOW,
        attempt_count=1,
        next_retry_at=_NOW,
    )


def _resolution(outcome: ResolutionOutcome, source: str | None) -> Resolution:
    listed = outcome in {
        ResolutionOutcome.RESOLVED,
        ResolutionOutcome.NOT_TOKEN_PRICED,
        ResolutionOutcome.PRICE_UNPARSEABLE,
    }
    return Resolution(
        outcome=outcome,
        catalog_model="vendor/model-x" if listed else None,
        catalog_source=source if listed else None,
        price=ModelPrice(3.0, 6.0) if outcome is ResolutionOutcome.RESOLVED else None,
        step="exact" if listed else None,
    )


def _expected_preservation(
    *,
    owner: str | None,
    current_state: str,
    outcome: ResolutionOutcome,
    proposed_source: str | None,
    serving: CatalogAvailability,
    reference: CatalogAvailability,
) -> bool:
    if outcome is ResolutionOutcome.PRICE_UNPARSEABLE:
        return True

    if current_state == "resolved":
        if outcome is not ResolutionOutcome.RESOLVED:
            return True
        if owner is not None and proposed_source != owner:
            return True

    def answered(source: str) -> bool:
        if source == _SERVING:
            return serving.authoritative
        if source == _REFERENCE:
            return reference.authoritative
        return False

    settled = current_state in {"resolved", "not_token_priced"}
    settling = outcome in {ResolutionOutcome.RESOLVED, ResolutionOutcome.NOT_TOKEN_PRICED}
    if settled and owner is not None and not answered(owner):
        return True
    if owner is None and settled and not settling and not (answered(_SERVING) and answered(_REFERENCE)):
        return True
    return settling and proposed_source == _REFERENCE and owner != proposed_source and not answered(_SERVING)


def test_preservation_policy_covers_owner_availability_state_and_outcome_matrix() -> None:
    owners = (_SERVING, _REFERENCE, None)
    availabilities = tuple(CatalogAvailability)
    current_states = ("resolved", "unresolved", "ambiguous", "not_token_priced", "unparseable")
    proposals = (
        (ResolutionOutcome.RESOLVED, _SERVING),
        (ResolutionOutcome.RESOLVED, _REFERENCE),
        (ResolutionOutcome.UNRESOLVED, None),
        (ResolutionOutcome.AMBIGUOUS, None),
        (ResolutionOutcome.NOT_TOKEN_PRICED, _SERVING),
        (ResolutionOutcome.NOT_TOKEN_PRICED, _REFERENCE),
        (ResolutionOutcome.PRICE_UNPARSEABLE, _SERVING),
        (ResolutionOutcome.PRICE_UNPARSEABLE, _REFERENCE),
    )

    for owner, serving, reference, current_state, proposal in product(
        owners,
        availabilities,
        availabilities,
        current_states,
        proposals,
    ):
        outcome, proposed_source = proposal
        actual = preservation_reason(
            _record(current_state, owner),
            _SERVING,
            _resolution(outcome, proposed_source),
            consultations=SourceConsultations(serving=serving, reference=reference),
        )
        expected = _expected_preservation(
            owner=owner,
            current_state=current_state,
            outcome=outcome,
            proposed_source=proposed_source,
            serving=serving,
            reference=reference,
        )
        assert (actual is not None) is expected, (
            owner,
            serving,
            reference,
            current_state,
            outcome,
            proposed_source,
        )
