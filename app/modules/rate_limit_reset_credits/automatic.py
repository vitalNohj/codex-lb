from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.clients.rate_limit_reset_credits import RateLimitResetCreditsSnapshot, ResetCreditItem
from app.db.models import Account, AccountStatus

AUTO_REDEEM_WINDOW_SECONDS = 5 * 60
_INELIGIBLE_STATUSES = frozenset({AccountStatus.PAUSED, AccountStatus.REAUTH_REQUIRED, AccountStatus.DEACTIVATED})


@dataclass(frozen=True, slots=True)
class AutomaticRedeemCandidate:
    request_id: str
    credit: ResetCreditItem


def can_poll_reset_credits(account: Account) -> bool:
    return account.status not in _INELIGIBLE_STATUSES and bool(account.chatgpt_account_id)


def automatic_redeem_candidate(
    account: Account,
    snapshot: RateLimitResetCreditsSnapshot | None,
    *,
    now: datetime,
    window_seconds: float = AUTO_REDEEM_WINDOW_SECONDS,
) -> AutomaticRedeemCandidate | None:
    """Find the credit due for automatic redemption, before settings and ledger checks."""
    if snapshot is None or snapshot.available_count <= 0 or not can_poll_reset_credits(account):
        return None
    available = [
        (_to_utc(credit.expires_at), credit)
        for credit in snapshot.credits
        if credit.status == "available" and credit.expires_at is not None
    ]
    if not available:
        return None
    expires_at, credit = min(available, key=lambda item: item[0])
    if not 0 <= (expires_at - now).total_seconds() <= window_seconds:
        return None
    # One automatic request per account and UTC expiry date, even if multiple
    # credits expire on that day. The ledger enforces this across replicas.
    digest = hashlib.sha256(f"{account.id}:{expires_at.date().isoformat()}".encode("utf-8")).hexdigest()[:32]
    return AutomaticRedeemCandidate(request_id=f"auto-reset-credit:{digest}", credit=credit)


def _to_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
