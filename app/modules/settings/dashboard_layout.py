"""Server-side visibility for dashboard cards and sections.

The stored JSON and these defaults are the contract the dashboard reads.
``conversations`` stays off until an operator turns it on. Every other flag
stays on, so a fresh install matches the previous dashboard except for that
card. The frontend copy of these defaults lives in
``frontend/src/features/dashboard/layout.ts`` and must keep the same flags.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

_LAYOUT_FIELDS = (
    "requests",
    "tokens",
    "estimated_cost",
    "conversations",
    "error_rate",
    "usage",
    "accounts",
    "request_logs",
)


@dataclass(frozen=True, slots=True)
class DashboardLayoutVisibility:
    requests: bool = True
    tokens: bool = True
    estimated_cost: bool = True
    conversations: bool = False
    error_rate: bool = True
    usage: bool = True
    accounts: bool = True
    request_logs: bool = True


def dump_dashboard_layout(layout: DashboardLayoutVisibility) -> str:
    payload = {name: bool(getattr(layout, name)) for name in _LAYOUT_FIELDS}
    return json.dumps(payload, separators=(",", ":"))


def parse_dashboard_layout(raw: str | None) -> DashboardLayoutVisibility:
    """Read a stored layout. Missing keys keep the dataclass defaults.

    ``None`` and ``""`` are the unset column (an in-memory row that has not
    been flushed, or a caller that has not stored a layout yet) and use the
    defaults. A non-object or a non-boolean flag is corrupt and raises.
    """

    if raw is None or raw == "":
        return DashboardLayoutVisibility()
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("dashboard_layout_json must be an object")
    defaults = DashboardLayoutVisibility()
    values: dict[str, bool] = {}
    for name in _LAYOUT_FIELDS:
        if name not in parsed:
            values[name] = bool(getattr(defaults, name))
            continue
        value = parsed[name]
        if not isinstance(value, bool):
            raise ValueError(f"dashboard_layout_json.{name} must be a boolean")
        values[name] = value
    return DashboardLayoutVisibility(**values)


def merge_dashboard_layout(
    current: DashboardLayoutVisibility,
    updates: Mapping[str, bool],
) -> DashboardLayoutVisibility:
    values = {name: bool(getattr(current, name)) for name in _LAYOUT_FIELDS}
    for name, value in updates.items():
        if name not in values:
            raise ValueError(f"unknown dashboard layout field {name}")
        if not isinstance(value, bool):
            raise ValueError(f"dashboard layout field {name} must be a boolean")
        values[name] = value
    return DashboardLayoutVisibility(**values)


DEFAULT_DASHBOARD_LAYOUT_JSON = dump_dashboard_layout(DashboardLayoutVisibility())


def sql_dashboard_layout_default() -> str:
    """SQL string literal for the column default.

    Pass the result to ``literal_column``. ``text()`` treats ``:true`` and
    ``:false`` inside the JSON as bind parameters and stores NULL.
    """

    return "'" + DEFAULT_DASHBOARD_LAYOUT_JSON.replace("'", "''") + "'"
