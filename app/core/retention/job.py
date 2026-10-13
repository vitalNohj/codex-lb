from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select

from app.core.config.settings import get_settings
from app.core.config.settings_cache import get_settings_cache
from app.core.utils.time import utcnow
from app.db.models import (
    AccountUsageRollupState,
    AdditionalUsageHistory,
    RequestLog,
    RequestUsageHourlyRollup,
    UsageHistory,
)
from app.db.session import get_background_session, sqlite_writer_section
from app.modules.accounts.usage_rollup import FOLD_LAG
from app.modules.accounts.usage_time_rollup import epoch_seconds
from app.modules.usage.repository import _clear_bulk_history_since_sqlite_cache

logger = logging.getLogger(__name__)

# Rows deleted per transaction; a large backlog drains across many short
# transactions instead of holding one long one.
BATCH_SIZE = 10_000


@dataclass(frozen=True, slots=True)
class EffectiveRetention:
    request_log_days: int
    usage_history_days: int
    hourly_rollup_days: int

    @property
    def enabled(self) -> bool:
        # The hourly-rollup window alone does not wake the pass: hourly
        # pruning applies only while request-log retention is enabled (the
        # hourly rollups must outlive raw; with raw retention disabled they
        # stay permanent — see _prune_hourly_rollups).
        return bool(self.request_log_days or self.usage_history_days)


async def get_effective_retention() -> EffectiveRetention:
    """Resolve the retention windows with dashboard-first precedence.

    A non-NULL dashboard value (SettingsCache-backed, so a dashboard change
    takes effect without restart) wins; while the dashboard value is unset the
    deprecated env alias applies; 0 means disabled at either layer.
    """
    env = get_settings()
    dashboard = await get_settings_cache().get()
    return EffectiveRetention(
        request_log_days=(
            env.request_log_retention_days
            if dashboard.request_log_retention_days is None
            else dashboard.request_log_retention_days
        ),
        usage_history_days=(
            env.usage_history_retention_days
            if dashboard.usage_history_retention_days is None
            else dashboard.usage_history_retention_days
        ),
        hourly_rollup_days=(
            env.hourly_rollup_retention_days
            if dashboard.hourly_rollup_retention_days is None
            else dashboard.hourly_rollup_retention_days
        ),
    )


async def run_retention_pass(*, now: datetime | None = None) -> dict[str, int]:
    """Prune aged rows per the effective retention settings. Returns rows deleted per table."""
    retention = await get_effective_retention()
    now = now or utcnow()
    deleted = {"request_logs": 0, "usage_history": 0, "additional_usage_history": 0, "hourly_rollups": 0}
    if retention.request_log_days:
        cutoff = now - timedelta(days=retention.request_log_days)
        deleted["request_logs"] = await _prune_request_logs(cutoff, now=now)
    if retention.usage_history_days:
        cutoff = now - timedelta(days=retention.usage_history_days)
        deleted["usage_history"] = await _prune_usage_history(cutoff)
        deleted["additional_usage_history"] = await _prune_additional_usage_history(cutoff)
    deleted["hourly_rollups"] = await _prune_hourly_rollups(now=now)
    total = sum(deleted.values())
    if total:
        logger.info(
            "Retention pruned rows request_logs=%s usage_history=%s additional_usage_history=%s hourly_rollups=%s",
            deleted["request_logs"],
            deleted["usage_history"],
            deleted["additional_usage_history"],
            deleted["hourly_rollups"],
        )
    return deleted


async def _prune_hourly_rollups(*, now: datetime) -> int:
    """Prune main hourly-rollup rows per the optional hourly retention.

    Off unless request-log retention is enabled. When enabled:

    - The effective window is the MAX of the hourly setting and the
      request-log window, so the hourly rollups always outlive raw (a
      shorter-than-raw hourly history would leave the upgrade repair and
      the rollup-served dashboard reads with statistics raw cannot recompute).
    - With raw retention disabled (0 = unlimited) hourly pruning is skipped
      entirely: pruning hours raw still holds would leave the upgrade
      repair and the non-UTC rollup-served history reads with statistics
      raw cannot recompute, while the hourly table is negligible next to
      unlimited raw.
    - Only hours STRICTLY below the daily watermark are pruned: those whole
      UTC days are already folded into ``request_usage_daily_rollups``,
      whose fold never revisits them (it only moves forward, and its
      re-fold windows start at its own watermark), so the pruned hours can
      never be re-read by the daily fold. The error satellite and the
      demand rollups have no coarser store and are never pruned here.

    No watermark means nothing is folded — skip entirely.
    """
    retention = await get_effective_retention()
    hourly_days = retention.hourly_rollup_days
    if not hourly_days:
        return 0
    if not retention.request_log_days:
        # Raw retention disabled (0 = unlimited): the hourly rollups stay
        # permanent. Pruning hours raw still covers would leave the upgrade
        # repair and the timezone-offset history unions unable to recompute
        # those statistics, and the hourly table is tiny next to unlimited
        # raw anyway.
        return 0
    # With both set the LONGER window wins so the hourly rollups never prune
    # history raw still keeps.
    effective_days = max(hourly_days, retention.request_log_days)
    cutoff = now - timedelta(days=effective_days)
    cutoff_epoch = epoch_seconds(cutoff)
    total = 0
    while True:
        async with get_background_session() as session:
            async with sqlite_writer_section():
                # FOR UPDATE: the prune gate must serialize with fold-state
                # mutations (watermark advances, escape-hatch resets) — same
                # discipline as the request-log prune.
                state = (
                    await session.execute(
                        select(AccountUsageRollupState.daily_folded_through)
                        .where(AccountUsageRollupState.id == 1)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if state is None:
                    return total
                daily_watermark_epoch = epoch_seconds(state)
                batch_ids = (
                    select(RequestUsageHourlyRollup.bucket_epoch)
                    .where(
                        RequestUsageHourlyRollup.bucket_epoch < cutoff_epoch,
                        RequestUsageHourlyRollup.bucket_epoch < daily_watermark_epoch,
                    )
                    .order_by(RequestUsageHourlyRollup.bucket_epoch.asc())
                    .limit(BATCH_SIZE)
                ).scalar_subquery()
                result = await session.execute(
                    delete(RequestUsageHourlyRollup)
                    .where(RequestUsageHourlyRollup.bucket_epoch.in_(batch_ids))
                    .returning(RequestUsageHourlyRollup.bucket_epoch)
                )
                await session.commit()
        deleted = len(result.scalars().all())
        total += deleted
        if deleted < BATCH_SIZE:
            return total


async def _prune_request_logs(cutoff: datetime, *, now: datetime) -> int:
    """Delete folded request-log rows older than the cutoff.

    Rows above the rollup watermark are never deleted: their contribution
    exists only in the live table, so pruning them would silently shrink
    lifetime account totals. No watermark (fold never ran) means skip.

    The effective watermark is the MIN of the lifetime fold watermark and the
    hourly and conversation time-axis watermarks: a raw row is only prunable
    once EVERY rollup that must outlive it has folded it. While either
    time-axis backfill is catching up (each watermark starts at the epoch),
    the min fails the currency check below and pruning pauses entirely — the
    pre-existing "never delete what is not folded" invariant extended to the
    time-axis rollups.

    Pruning also requires the fold to be CURRENT (watermark within two fold
    lags of now) and stays a full fold lag below it. Summary reads load the
    watermark and the live tail in separate statements; a fold committing
    between them can advance the watermark, and deleting rows from that
    just-folded window would make the reader's tail miss rows its (older)
    folded sums never contained. A reader's loaded watermark is at most one
    steady-state fold advance behind the current one - far less than the
    fold lag - so rows a lag below a current watermark are safe; while the
    fold is catching up (initial backfill, stalled scheduler), skip
    entirely.

    Pruning also pauses while a post-upgrade repair is pending
    (``upgrade_repair_from`` set). The repair refolds hourly and demand
    buckets from raw rows, starting no earlier than the first hour the
    surviving rows fully cover. A row pruned before the repair reaches its
    hour would leave that bucket holding the pre-repair figures for good, and
    capping the cutoff at the marker is not enough: deleting the oldest rows
    moves the repair's start past the marker. The repair clears the marker
    when it finishes, and pruning resumes on the next pass.
    """
    total = 0
    while True:
        async with get_background_session() as session:
            async with sqlite_writer_section():
                # FOR UPDATE: the batch's prune decision must serialize with
                # anything mutating the fold state in another transaction —
                # in particular the operator escape hatch (rollup truncate +
                # watermark reset). An unlocked read could capture the old
                # watermark, the reset could commit, and this batch would
                # then prune raw rows whose folded statistics were just
                # truncated — recoverable from neither side. With the row
                # lock held through the batch, the reset either commits
                # first (this read sees the epoch watermark and pruning
                # pauses) or waits until the batch's delete has committed.
                state = (
                    await session.execute(
                        select(
                            AccountUsageRollupState.folded_through,
                            AccountUsageRollupState.hourly_folded_through,
                            AccountUsageRollupState.conversation_folded_through,
                            AccountUsageRollupState.upgrade_repair_from,
                        )
                        .where(AccountUsageRollupState.id == 1)
                        .with_for_update()
                    )
                ).first()
                if state is None:
                    if total == 0:
                        logger.info("Retention: skipping request_logs pruning (no rollup watermark yet)")
                    return total
                if state.upgrade_repair_from is not None:
                    if total == 0:
                        logger.info(
                            "Retention: skipping request_logs pruning (hourly rollup repair pending from %s)",
                            state.upgrade_repair_from.isoformat(),
                        )
                    return total
                watermark = min(
                    state.folded_through,
                    state.hourly_folded_through,
                    state.conversation_folded_through,
                )
                if watermark < now - 2 * FOLD_LAG:
                    if total == 0:
                        logger.info(
                            "Retention: skipping request_logs pruning (fold watermark %s not current)",
                            watermark.isoformat(),
                        )
                    return total
                effective_cutoff = min(cutoff, watermark - FOLD_LAG)
                # Oldest-first batches keep min(requested_at) a contiguous
                # retention frontier: an interrupted pass never leaves
                # deleted holes above the oldest surviving row, which the
                # rollup-served listing count relies on when clamping its
                # folded window to listable history.
                batch_ids = (
                    select(RequestLog.id)
                    .where(RequestLog.requested_at < effective_cutoff)
                    .order_by(RequestLog.requested_at.asc(), RequestLog.id.asc())
                    .limit(BATCH_SIZE)
                ).scalar_subquery()
                result = await session.execute(
                    delete(RequestLog).where(RequestLog.id.in_(batch_ids)).returning(RequestLog.id)
                )
                await session.commit()
        deleted = len(result.scalars().all())
        total += deleted
        if deleted < BATCH_SIZE:
            return total


async def _prune_usage_history(cutoff: datetime) -> int:
    # Materialize the protected id set once per pass instead of embedding
    # the GROUP BY subquery in every batch statement (which would rescan the
    # whole table per 10k batch, under the SQLite writer lock). New rows
    # arriving mid-pass are newer than the cutoff and survive on age; their
    # identity's previously-latest row also surviving is merely conservative.
    #
    # "Latest" follows the product's ordering (recorded_at first, not id:
    # latest_by_account orders by recorded_at desc), so out-of-chronology
    # inserts cannot lose the last-known sample; every row tied at the
    # identity's max recorded_at is protected, a safe superset of any
    # tie-break the readers apply.
    window_expr = func.coalesce(UsageHistory.window, "primary")
    latest_ts = (
        select(
            UsageHistory.account_id.label("aid"),
            window_expr.label("win"),
            func.max(UsageHistory.recorded_at).label("ts"),
        )
        .group_by(UsageHistory.account_id, window_expr)
        .subquery("latest_ts")
    )
    protected_stmt = select(UsageHistory.id).join(
        latest_ts,
        (UsageHistory.account_id == latest_ts.c.aid)
        & (window_expr == latest_ts.c.win)
        & (UsageHistory.recorded_at == latest_ts.c.ts),
    )
    deleted = await _batched_prune(
        UsageHistory,
        cutoff_condition=UsageHistory.recorded_at < cutoff,
        protected_stmt=protected_stmt,
    )
    if deleted:
        _clear_bulk_history_since_sqlite_cache()
    return deleted


async def _prune_additional_usage_history(cutoff: datetime) -> int:
    latest_ts = (
        select(
            AdditionalUsageHistory.account_id.label("aid"),
            AdditionalUsageHistory.quota_key.label("qk"),
            AdditionalUsageHistory.window.label("win"),
            func.max(AdditionalUsageHistory.recorded_at).label("ts"),
        )
        .group_by(
            AdditionalUsageHistory.account_id,
            AdditionalUsageHistory.quota_key,
            AdditionalUsageHistory.window,
        )
        .subquery("latest_additional_ts")
    )
    protected_stmt = select(AdditionalUsageHistory.id).join(
        latest_ts,
        (AdditionalUsageHistory.account_id == latest_ts.c.aid)
        & (AdditionalUsageHistory.quota_key == latest_ts.c.qk)
        & (AdditionalUsageHistory.window == latest_ts.c.win)
        & (AdditionalUsageHistory.recorded_at == latest_ts.c.ts),
    )
    return await _batched_prune(
        AdditionalUsageHistory,
        cutoff_condition=AdditionalUsageHistory.recorded_at < cutoff,
        protected_stmt=protected_stmt,
    )


async def _batched_prune(model, *, cutoff_condition, protected_stmt) -> int:
    async with get_background_session() as session:
        protected_ids = list((await session.execute(protected_stmt)).scalars().all())

    total = 0
    while True:
        async with get_background_session() as session:
            async with sqlite_writer_section():
                conditions = [cutoff_condition]
                if protected_ids:
                    conditions.append(model.id.not_in(protected_ids))
                batch_ids = select(model.id).where(*conditions).limit(BATCH_SIZE).scalar_subquery()
                result = await session.execute(delete(model).where(model.id.in_(batch_ids)).returning(model.id))
                await session.commit()
        deleted = len(result.scalars().all())
        total += deleted
        if deleted < BATCH_SIZE:
            return total
