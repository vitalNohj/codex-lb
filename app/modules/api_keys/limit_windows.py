from __future__ import annotations

from datetime import datetime, timedelta

from app.db.models import LimitWindow

# A lifetime limit never resets. Its ``reset_at`` stays NOT NULL and is pinned
# to this far-future sentinel, so the reset sweeps (``reset_at < now``) skip it
# and the reservation compare-and-swap on ``reset_at`` keeps working unchanged.
# Stored naive, like every other ``reset_at`` (UTC wall clock).
LIFETIME_RESET_AT = datetime(9999, 12, 31)


def is_lifetime_window(window: LimitWindow) -> bool:
    return window == LimitWindow.LIFETIME


def public_limit_reset_at(window: LimitWindow, reset_at: datetime) -> datetime | None:
    """The reset time to show a client: ``None`` for a limit that never resets."""
    return None if is_lifetime_window(window) else reset_at


def next_limit_reset(now: datetime, window: LimitWindow) -> datetime:
    delta = limit_window_delta(window)
    if delta is None:
        return LIFETIME_RESET_AT
    return now + delta


def advance_limit_reset(reset_at: datetime, now: datetime, window: LimitWindow) -> datetime:
    delta = limit_window_delta(window)
    if delta is None:
        return LIFETIME_RESET_AT
    next_reset = reset_at
    while next_reset <= now:
        next_reset += delta
    return next_reset


def limit_window_delta(window: LimitWindow) -> timedelta | None:
    """Return the rolling length of a window, or ``None`` for one that never resets.

    Raises ``ValueError`` for a window this module does not know, so a new
    ``LimitWindow`` value cannot silently inherit some other window's reset.
    """
    match window:
        case LimitWindow.FIVE_HOURS:
            return timedelta(hours=5)
        case LimitWindow.DAILY:
            return timedelta(days=1)
        case LimitWindow.WEEKLY | LimitWindow.SEVEN_DAYS:
            return timedelta(days=7)
        case LimitWindow.MONTHLY:
            return timedelta(days=30)
        case LimitWindow.LIFETIME:
            return None
    raise ValueError(f"Unsupported API key limit window: {window!r}")
