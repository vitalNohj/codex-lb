"""Checks for CLIProxyAPI credential field edits.

Weight, priority, excluded models, and an operator-chosen prefix are the
fields the panel writes. A stored prefix is replaced only when the operator
sends a new one. The capacity router may fill an empty prefix; it does not
clear or replace one.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.core.exceptions import DashboardBadRequestError, DashboardConflictError
from app.modules.claude_sidecar.excluded_models import MAX_PATTERN_LENGTH, MAX_PATTERNS, normalize_excluded_models
from app.modules.claude_sidecar.quota import SidecarAuthQuota

MAX_WEIGHT = 1_000_000
MAX_PRIORITY = 1_000_000
_PREFIX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def prefix_or_none(value: str | None) -> str | None:
    """Return a single-segment CLIProxyAPI prefix, or None when it is unusable."""

    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or _PREFIX_RE.fullmatch(text) is None:
        return None
    return text


def validate_prefix(prefix: str) -> str:
    text = prefix_or_none(prefix)
    if text is None:
        raise DashboardBadRequestError(
            "Prefix must be a single path segment of letters, numbers, dots, underscores, or hyphens"
        )
    return text


def reject_duplicate_prefix(prefix: str, others: Iterable[str | None]) -> None:
    folded = prefix.casefold()
    for item in others:
        if isinstance(item, str) and item.strip().casefold() == folded:
            raise DashboardConflictError("That prefix is already used by another CLIProxyAPI account")


@dataclass(frozen=True, slots=True)
class CredentialFieldChange:
    weight: int | None = None
    priority: int | None = None
    excluded_models: tuple[str, ...] | None = None
    prefix: str | None = None
    update_weight: bool = False
    update_priority: bool = False
    update_excluded_models: bool = False
    update_prefix: bool = False

    @property
    def changed_fields(self) -> tuple[str, ...]:
        names: list[str] = []
        if self.update_weight:
            names.append("weight")
        if self.update_priority:
            names.append("priority")
        if self.update_excluded_models:
            names.append("excluded_models")
        if self.update_prefix:
            names.append("prefix")
        return tuple(names)

    def is_empty(self) -> bool:
        return not self.changed_fields


def disabling_last_enabled_account(
    accounts: Sequence[SidecarAuthQuota],
    *,
    name: str,
    disabled: bool,
) -> bool:
    """True when this write would leave no enabled CLIProxyAPI account."""

    if not disabled:
        return False
    target = next((account for account in accounts if account.name == name), None)
    if target is None or target.disabled:
        return False
    return sum(1 for account in accounts if not account.disabled) <= 1


def validate_weight(weight: int) -> int:
    if isinstance(weight, bool) or not isinstance(weight, int):
        raise DashboardBadRequestError("Weight must be an integer")
    if weight < 0 or weight > MAX_WEIGHT:
        raise DashboardBadRequestError(f"Weight must be between 0 and {MAX_WEIGHT}")
    return weight


def validate_priority(priority: int) -> int:
    if isinstance(priority, bool) or not isinstance(priority, int):
        raise DashboardBadRequestError("Priority must be an integer")
    if priority < -MAX_PRIORITY or priority > MAX_PRIORITY:
        raise DashboardBadRequestError(f"Priority must be between -{MAX_PRIORITY} and {MAX_PRIORITY}")
    return priority


def validate_excluded_models(patterns: Sequence[str]) -> tuple[str, ...]:
    raw = list(patterns)
    normalized = normalize_excluded_models(raw)
    if normalized != raw:
        raise DashboardBadRequestError(
            "Excluded models must already be trimmed patterns without commas, "
            f"at most {MAX_PATTERNS} entries of {MAX_PATTERN_LENGTH} characters"
        )
    return tuple(normalized)
