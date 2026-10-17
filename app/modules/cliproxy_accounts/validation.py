"""Checks for CLIProxyAPI credential field edits.

Weight, priority, and excluded models are the fields the panel writes.
A prefix already stored on the credential is left to CLIProxyAPI.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.core.exceptions import DashboardBadRequestError
from app.modules.claude_sidecar.excluded_models import MAX_PATTERN_LENGTH, MAX_PATTERNS, normalize_excluded_models
from app.modules.claude_sidecar.quota import SidecarAuthQuota

MAX_WEIGHT = 1_000_000
MAX_PRIORITY = 1_000_000


@dataclass(frozen=True, slots=True)
class CredentialFieldChange:
    weight: int | None = None
    priority: int | None = None
    excluded_models: tuple[str, ...] | None = None
    update_weight: bool = False
    update_priority: bool = False
    update_excluded_models: bool = False

    @property
    def changed_fields(self) -> tuple[str, ...]:
        names: list[str] = []
        if self.update_weight:
            names.append("weight")
        if self.update_priority:
            names.append("priority")
        if self.update_excluded_models:
            names.append("excluded_models")
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
