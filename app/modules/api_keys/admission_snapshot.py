"""Process-local copy of a reservation's items for the request that created it.

Settlement of that request would otherwise re-read the rows it just wrote.
The database remains the fallback when this process never reserved the id
(another worker, a restart, or the stale-release sweep).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.api_keys.repository import UsageReservationItemData

_ADMISSION_SNAPSHOT_CAP = 10_000
_snapshots: dict[str, tuple[UsageReservationItemData, ...]] = {}


def remember_admission_items(reservation_id: str, items: list[UsageReservationItemData]) -> None:
    if reservation_id in _snapshots:
        del _snapshots[reservation_id]
    _snapshots[reservation_id] = tuple(items)
    while len(_snapshots) > _ADMISSION_SNAPSHOT_CAP:
        oldest = next(iter(_snapshots))
        del _snapshots[oldest]


def recall_admission_items(reservation_id: str) -> tuple[UsageReservationItemData, ...] | None:
    return _snapshots.get(reservation_id)


def forget_admission_items(reservation_id: str) -> None:
    _snapshots.pop(reservation_id, None)


def clear_admission_items() -> None:
    _snapshots.clear()
