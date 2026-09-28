"""Tell when no Claude auth can serve because the quota poller holds all of them.

The quota poller disables an exhausted CLIProxyAPI Claude auth until its usage
window resets. Once every Claude auth is disabled, CLIProxyAPI has no provider
registered for any Claude model and answers
``400 unknown provider for model ...``: a request error a client will not retry,
for a condition that clears on its own at a known time. This module reads the
stored quota snapshot and reports that time, so the dispatcher can wait for it
or answer ``429`` with ``Retry-After`` instead. It does not talk to CLIProxyAPI.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.modules.claude_sidecar.quota import SidecarQuotaSnapshot, snapshot_from_json

# CLIProxyAPI's answer when no enabled auth registers the requested model.
_UNKNOWN_PROVIDER_MARKER = "unknown provider for model"


def all_claude_auths_held_until(snapshot: SidecarQuotaSnapshot | None) -> datetime | None:
    """Return the earliest hold release when no Claude auth is enabled, else ``None``.

    Every Claude auth in the snapshot must be disabled, and at least one of them
    must be under an unreleased poller hold. An auth that is disabled with no
    such hold is an operator pause and never comes back on its own, so a snapshot
    made only of those is not a hold. The returned instant may already be past
    when the poller has not yet run to enable that auth again.
    """
    if not no_claude_auth_enabled(snapshot):
        return None
    assert snapshot is not None
    names = {account.name for account in snapshot.accounts if account.name}
    releases = [_as_utc(hold.until) for hold in snapshot.rate_limit_holds if hold.name in names and not hold.released]
    return min(releases) if releases else None


def no_claude_auth_enabled(snapshot: SidecarQuotaSnapshot | None) -> bool:
    """Whether a healthy snapshot lists Claude auths and every one is disabled."""
    if snapshot is None or snapshot.status != "healthy":
        return False
    named = [account for account in snapshot.accounts if account.name]
    return bool(named) and all(account.disabled for account in named)


def next_hold_release(snapshot: SidecarQuotaSnapshot | None, now: datetime) -> datetime | None:
    """Return the earliest future release among the snapshot's unreleased holds."""
    if snapshot is None:
        return None
    now_utc = _as_utc(now)
    releases = [
        _as_utc(hold.until) for hold in snapshot.rate_limit_holds if not hold.released and _as_utc(hold.until) > now_utc
    ]
    return min(releases) if releases else None


def is_unknown_provider_message(message: str) -> bool:
    return _UNKNOWN_PROVIDER_MARKER in message.casefold()


class StoredSnapshotReader:
    """Parse the stored snapshot JSON once per distinct value.

    The dispatcher reads it on every Claude request; the settings cache hands
    back the same string until the poller writes a new one.
    """

    def __init__(self) -> None:
        self._raw: str | None = None
        self._snapshot: SidecarQuotaSnapshot | None = None

    def read(self, raw: str | None) -> SidecarQuotaSnapshot | None:
        if raw != self._raw:
            self._snapshot = snapshot_from_json(raw)
            self._raw = raw
        return self._snapshot


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
