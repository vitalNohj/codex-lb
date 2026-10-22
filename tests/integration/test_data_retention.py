from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

import app.core.retention.job as retention_job
<<<<<<< 22625a07e
from app.core.config.settings import Settings, get_settings
||||||| 84fde5a1e
from app.core.config.settings import Settings, get_settings
=======
>>>>>>> 72630bbfe
from app.core.config.settings_cache import get_settings_cache
from app.core.crypto import TokenEncryptor
from app.core.retention.job import get_effective_retention, run_retention_pass
from app.core.utils.time import utcnow
from app.db.models import (
    Account,
    AccountStatus,
    AccountUsageRollupState,
    AdditionalUsageHistory,
    RequestLog,
    RequestUsageDailyRollup,
    RequestUsageHourlyRollup,
    UsageHistory,
)
from app.db.session import SessionLocal
from app.modules.accounts.repository import AccountsRepository
from app.modules.accounts.usage_rollup import run_fold_pass
<<<<<<< 22625a07e
from app.modules.accounts.usage_time_rollup import (
    run_conversation_fold_pass,
    run_daily_fold_pass,
    run_hourly_fold_pass,
)
||||||| 84fde5a1e
from app.modules.accounts.usage_time_rollup import run_conversation_fold_pass, run_hourly_fold_pass
=======
from app.modules.accounts.usage_time_rollup import run_conversation_fold_pass, run_hourly_fold_pass
from app.modules.reports.rollup import run_report_fold_pass
>>>>>>> 72630bbfe
from app.modules.request_logs.repository import RequestLogsRepository
from app.modules.settings.repository import SettingsRepository

pytestmark = pytest.mark.integration


def _make_account(account_id: str, email: str) -> Account:
    encryptor = TokenEncryptor()
    return Account(
        id=account_id,
        email=email,
        plan_type="plus",
        access_token_encrypted=encryptor.encrypt("access"),
        refresh_token_encrypted=encryptor.encrypt("refresh"),
        id_token_encrypted=encryptor.encrypt("id"),
        last_refresh=utcnow(),
        status=AccountStatus.ACTIVE,
        deactivation_reason=None,
    )


async def _add_log(
    logs_repo: RequestLogsRepository, *, account_id: str, request_id: str, requested_at, conversation_id=None
):
    return await logs_repo.add_log(
        account_id=account_id,
        request_id=request_id,
        model="gpt-5.1-codex",
        input_tokens=100,
        output_tokens=50,
        latency_ms=100,
        status="success",
        error_code=None,
        requested_at=requested_at,
        cost_usd=0.01,
        conversation_id=conversation_id,
    )


async def _set_retention(*, request_logs: int | None = 0, usage_history: int | None = 0) -> None:
    """Store the dashboard retention windows (NULL = never configured, 0 = disabled)."""
    async with SessionLocal() as session:
        row = await SettingsRepository(session).get_or_create()
        row.request_log_retention_days = request_logs
        row.usage_history_retention_days = usage_history
        await session.commit()
    await get_settings_cache().invalidate()


@pytest.mark.asyncio
async def test_retention_disabled_by_default_deletes_nothing(db_setup):
    now = utcnow()
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        logs_repo = RequestLogsRepository(session)
        await accounts_repo.upsert(_make_account("acc_off", "off@example.com"))
        await _add_log(logs_repo, account_id="acc_off", request_id="req_old", requested_at=now - timedelta(days=400))
        session.add(UsageHistory(account_id="acc_off", used_percent=10.0, recorded_at=now - timedelta(days=400)))
        await session.commit()

    deleted = await run_retention_pass(now=now)
    assert deleted == {"request_logs": 0, "usage_history": 0, "additional_usage_history": 0, "hourly_rollups": 0}


@pytest.mark.asyncio
async def test_request_log_pruning_respects_watermark_and_preserves_totals(async_client, db_setup, monkeypatch):
    now = utcnow()
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        logs_repo = RequestLogsRepository(session)
        await accounts_repo.upsert(_make_account("acc_ret", "ret@example.com"))
        await _add_log(logs_repo, account_id="acc_ret", request_id="req_60d", requested_at=now - timedelta(days=60))
        await _add_log(logs_repo, account_id="acc_ret", request_id="req_40d", requested_at=now - timedelta(days=40))
        await _add_log(logs_repo, account_id="acc_ret", request_id="req_1d", requested_at=now - timedelta(days=1))

    await run_fold_pass(now=now)
    await run_hourly_fold_pass(now=now)
    await run_conversation_fold_pass(now=now)
    await run_report_fold_pass(now=now)

    async def _request_usage():
        response = await async_client.get("/api/accounts")
        assert response.status_code == 200
        accounts = {item["accountId"]: item for item in response.json()["accounts"]}
        return accounts["acc_ret"]["requestUsage"]

    before = await _request_usage()
    assert before["requestCount"] == 3

    await _set_retention(request_logs=30)
    deleted = await run_retention_pass(now=now)
    assert deleted["request_logs"] == 2

    async with SessionLocal() as session:
        remaining = (await session.execute(select(RequestLog.request_id))).scalars().all()
    assert sorted(remaining) == ["req_1d"]

    assert await _request_usage() == before


@pytest.mark.asyncio
async def test_request_log_pruning_skipped_without_watermark(db_setup, monkeypatch):
    now = utcnow()
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        logs_repo = RequestLogsRepository(session)
        await accounts_repo.upsert(_make_account("acc_nofold", "nofold@example.com"))
        await _add_log(logs_repo, account_id="acc_nofold", request_id="req_old", requested_at=now - timedelta(days=400))

    await _set_retention(request_logs=30)
    deleted = await run_retention_pass(now=now)
    assert deleted["request_logs"] == 0
    async with SessionLocal() as session:
        assert (await session.execute(select(RequestLog.id))).scalars().all()


@pytest.mark.asyncio
async def test_usage_history_pruning_keeps_latest_per_identity(db_setup, monkeypatch):
    now = utcnow()
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        await accounts_repo.upsert(_make_account("acc_idle", "idle@example.com"))
        for days_ago in (200, 150, 100):
            session.add(
                UsageHistory(
                    account_id="acc_idle",
                    window="primary",
                    used_percent=float(days_ago),
                    recorded_at=now - timedelta(days=days_ago),
                )
            )
            session.add(
                AdditionalUsageHistory(
                    account_id="acc_idle",
                    quota_key="gpt-5-pro",
                    limit_name="gpt5pro",
                    metered_feature="gpt5pro",
                    window="primary",
                    used_percent=float(days_ago),
                    recorded_at=now - timedelta(days=days_ago),
                )
            )
        await session.commit()

    await _set_retention(usage_history=45)
    deleted = await run_retention_pass(now=now)
    assert deleted["usage_history"] == 2
    assert deleted["additional_usage_history"] == 2

    async with SessionLocal() as session:
        usage_rows = (await session.execute(select(UsageHistory))).scalars().all()
        additional_rows = (await session.execute(select(AdditionalUsageHistory))).scalars().all()
    assert len(usage_rows) == 1
    assert usage_rows[0].used_percent == 100.0
    assert len(additional_rows) == 1
    assert additional_rows[0].used_percent == 100.0


@pytest.mark.asyncio
async def test_pruning_drains_backlog_across_batches(db_setup, monkeypatch):
    now = utcnow()
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        logs_repo = RequestLogsRepository(session)
        await accounts_repo.upsert(_make_account("acc_batch", "batch@example.com"))
        for index in range(5):
            await _add_log(
                logs_repo,
                account_id="acc_batch",
                request_id=f"req_{index}",
                requested_at=now - timedelta(days=60, minutes=index),
            )

    await run_fold_pass(now=now)
    await run_hourly_fold_pass(now=now)
    await run_conversation_fold_pass(now=now)
    await run_report_fold_pass(now=now)
    await _set_retention(request_logs=30)
    monkeypatch.setattr(retention_job, "BATCH_SIZE", 2)
    deleted = await run_retention_pass(now=now)
    assert deleted["request_logs"] == 5
    async with SessionLocal() as session:
        assert (await session.execute(select(RequestLog.id))).scalars().all() == []


@pytest.mark.asyncio
async def test_request_log_pruning_skipped_while_fold_is_not_current(async_client, db_setup, monkeypatch):
    """A stalled fold (watermark older than two fold lags) must skip pruning
    entirely: unfolded rows above the watermark would otherwise be lost, and
    concurrent readers hold watermarks near the stale one."""
    now = utcnow()
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        logs_repo = RequestLogsRepository(session)
        await accounts_repo.upsert(_make_account("acc_stall", "stall@example.com"))
        await _add_log(logs_repo, account_id="acc_stall", request_id="req_60d", requested_at=now - timedelta(days=60))
        await _add_log(logs_repo, account_id="acc_stall", request_id="req_40d", requested_at=now - timedelta(days=40))
        await _add_log(logs_repo, account_id="acc_stall", request_id="req_1d", requested_at=now - timedelta(days=1))

    # Fold stalled 50 days ago: watermark = (now - 50d) - FOLD_LAG.
    await run_fold_pass(now=now - timedelta(days=50))
    await run_hourly_fold_pass(now=now - timedelta(days=50))
    await run_conversation_fold_pass(now=now - timedelta(days=50))

    async def _request_usage():
        response = await async_client.get("/api/accounts")
        assert response.status_code == 200
        accounts = {item["accountId"]: item for item in response.json()["accounts"]}
        return accounts["acc_stall"]["requestUsage"]

    before = await _request_usage()
    assert before["requestCount"] == 3

    await _set_retention(request_logs=30)
    deleted = await run_retention_pass(now=now)
    assert deleted["request_logs"] == 0

    async with SessionLocal() as session:
        remaining = (await session.execute(select(RequestLog.request_id))).scalars().all()
    assert sorted(remaining) == ["req_1d", "req_40d", "req_60d"]

    assert await _request_usage() == before


@pytest.mark.asyncio
async def test_request_log_pruning_skipped_while_hourly_backfill_behind(db_setup, monkeypatch):
    """min-gate: a current lifetime watermark alone must not enable pruning
    while the hourly time-axis backfill has not caught up (its watermark
    still at the epoch) — pruning unfolded raw would leave permanent holes
    in the time-series rollups. Once the hourly fold catches up, pruning
    resumes and the folded buckets survive it unchanged."""
    from sqlalchemy import select as sa_select

    from app.db.models import RequestDemandQuarterRollup, RequestUsageHourlyRollup

    now = utcnow()
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        logs_repo = RequestLogsRepository(session)
        await accounts_repo.upsert(_make_account("acc_gate", "gate@example.com"))
        await _add_log(logs_repo, account_id="acc_gate", request_id="req_60d", requested_at=now - timedelta(days=60))
        await _add_log(logs_repo, account_id="acc_gate", request_id="req_1d", requested_at=now - timedelta(days=1))

    # Lifetime fold current, hourly fold never ran (watermark at epoch).
    await run_fold_pass(now=now)
    await _set_retention(request_logs=30)
    deleted = await run_retention_pass(now=now)
    assert deleted["request_logs"] == 0

    # Hourly fold catches up -> min watermark is current -> pruning resumes.
    await run_hourly_fold_pass(now=now)
    await run_conversation_fold_pass(now=now)
    await run_report_fold_pass(now=now)
    async with SessionLocal() as session:
        hourly_before = sorted(
            (await session.execute(sa_select(RequestUsageHourlyRollup))).scalars().all(),
            key=lambda row: (row.bucket_epoch, row.account_id, row.model),
        )
        hourly_before = [
            (row.bucket_epoch, row.account_id, row.request_count, row.input_tokens) for row in hourly_before
        ]
        demand_before = len((await session.execute(sa_select(RequestDemandQuarterRollup))).scalars().all())
    assert hourly_before  # the 60d row folded

    deleted = await run_retention_pass(now=now)
    assert deleted["request_logs"] == 1

    # Folded time-axis buckets are untouched by raw pruning.
    async with SessionLocal() as session:
        hourly_after = sorted(
            (await session.execute(sa_select(RequestUsageHourlyRollup))).scalars().all(),
            key=lambda row: (row.bucket_epoch, row.account_id, row.model),
        )
        hourly_after = [(row.bucket_epoch, row.account_id, row.request_count, row.input_tokens) for row in hourly_after]
        demand_after = len((await session.execute(sa_select(RequestDemandQuarterRollup))).scalars().all())
    assert hourly_after == hourly_before
    assert demand_after == demand_before


@pytest.mark.asyncio
async def test_request_log_pruning_skipped_while_hourly_fold_stalled(db_setup, monkeypatch):
    """min-gate: a stalled HOURLY watermark (older than two fold lags) must
    pause pruning even though the lifetime fold is perfectly current."""
    now = utcnow()
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        logs_repo = RequestLogsRepository(session)
        await accounts_repo.upsert(_make_account("acc_hstall", "hstall@example.com"))
        await _add_log(logs_repo, account_id="acc_hstall", request_id="req_60d", requested_at=now - timedelta(days=60))
        await _add_log(logs_repo, account_id="acc_hstall", request_id="req_1d", requested_at=now - timedelta(days=1))

    await run_hourly_fold_pass(now=now - timedelta(days=50))
    await run_conversation_fold_pass(now=now - timedelta(days=50))
    await run_fold_pass(now=now)

    await _set_retention(request_logs=30)
    deleted = await run_retention_pass(now=now)
    assert deleted["request_logs"] == 0
    async with SessionLocal() as session:
        remaining = (await session.execute(select(RequestLog.request_id))).scalars().all()
    assert sorted(remaining) == ["req_1d", "req_60d"]


@pytest.mark.asyncio
async def test_request_log_pruning_skipped_while_conversation_backfill_behind(db_setup, monkeypatch):
    """min-gate: the conversation satellite participates in the prune gate —
    lifetime and hourly currency alone must not enable pruning while the
    conversation backfill is still at the epoch, or raw the satellite never
    folded would be lost. Once it catches up, pruning resumes and the folded
    presence survives the prune."""
    from sqlalchemy import select as sa_select

    from app.db.models import RequestConversationHourlyRollup

    now = utcnow()
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        logs_repo = RequestLogsRepository(session)
        await accounts_repo.upsert(_make_account("acc_cgate", "cgate@example.com"))
        await _add_log(
            logs_repo,
            account_id="acc_cgate",
            request_id="req_60d",
            requested_at=now - timedelta(days=60),
            conversation_id="conv_gate",
        )
        await _add_log(logs_repo, account_id="acc_cgate", request_id="req_1d", requested_at=now - timedelta(days=1))

    await run_fold_pass(now=now)
    await run_hourly_fold_pass(now=now)
    await _set_retention(request_logs=30)
    assert (await run_retention_pass(now=now))["request_logs"] == 0

    await run_conversation_fold_pass(now=now)
    await run_report_fold_pass(now=now)
    assert (await run_retention_pass(now=now))["request_logs"] == 1
    async with SessionLocal() as session:
        presence = (await session.execute(sa_select(RequestConversationHourlyRollup))).scalars().all()
    assert [(row.conversation_id, row.request_count) for row in presence] == [("conv_gate", 1)]


@pytest.mark.asyncio
async def test_request_log_pruning_paused_while_upgrade_repair_pending(db_setup, monkeypatch):
    """A pending post-upgrade repair pauses pruning even when every watermark
    is current. The repair refolds buckets from raw rows and starts no earlier
    than the first hour the surviving rows fully cover, so a row pruned first
    would leave its bucket holding pre-repair figures for good. Once the
    repair clears the marker, pruning resumes."""
    from sqlalchemy import update

    from app.db.models import AccountUsageRollupState
    from app.modules.accounts.usage_time_rollup import floor_to_hour

    now = utcnow()
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        logs_repo = RequestLogsRepository(session)
        await accounts_repo.upsert(_make_account("acc_repair", "repair@example.com"))
        await _add_log(logs_repo, account_id="acc_repair", request_id="req_60d", requested_at=now - timedelta(days=60))
        await _add_log(logs_repo, account_id="acc_repair", request_id="req_1d", requested_at=now - timedelta(days=1))

    await run_fold_pass(now=now)
    await run_hourly_fold_pass(now=now)
    await run_conversation_fold_pass(now=now)
    # What a cost backfill migration leaves behind after repricing folded rows.
    async with SessionLocal() as session:
        await session.execute(
            update(AccountUsageRollupState).values(upgrade_repair_from=floor_to_hour(now - timedelta(days=2)))
        )
        await session.commit()

    _set_retention(monkeypatch, request_logs=30)
    assert (await run_retention_pass(now=now))["request_logs"] == 0
    async with SessionLocal() as session:
        remaining = (await session.execute(select(RequestLog.request_id))).scalars().all()
    assert sorted(remaining) == ["req_1d", "req_60d"]

    # The next hourly pass completes the repair and clears the marker.
    await run_hourly_fold_pass(now=now)
    async with SessionLocal() as session:
        marker = (await session.execute(select(AccountUsageRollupState.upgrade_repair_from))).scalar_one()
    assert marker is None

    assert (await run_retention_pass(now=now))["request_logs"] == 1
    async with SessionLocal() as session:
        remaining = (await session.execute(select(RequestLog.request_id))).scalars().all()
    assert remaining == ["req_1d"]


@pytest.mark.asyncio
async def test_usage_history_protects_latest_by_recorded_at_not_insert_order(db_setup, monkeypatch):
    """Out-of-chronology inserts: the row the product treats as latest (max
    recorded_at) must survive even when a later-inserted row carries an older
    recorded_at (and a higher id)."""
    now = utcnow()
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        await accounts_repo.upsert(_make_account("acc_ooo", "ooo@example.com"))
        # Inserted first: the chronologically-latest sample (lower id).
        session.add(
            UsageHistory(
                account_id="acc_ooo", window="primary", used_percent=55.0, recorded_at=now - timedelta(days=100)
            )
        )
        # Inserted later: an OLDER sample backfilled afterwards (higher id).
        session.add(
            UsageHistory(
                account_id="acc_ooo", window="primary", used_percent=11.0, recorded_at=now - timedelta(days=180)
            )
        )
        await session.commit()

    await _set_retention(usage_history=45)
    deleted = await run_retention_pass(now=now)
    assert deleted["usage_history"] == 1

    async with SessionLocal() as session:
        rows = (await session.execute(select(UsageHistory))).scalars().all()
    assert len(rows) == 1
    assert rows[0].used_percent == 55.0


@pytest.mark.asyncio
async def test_usage_history_pruning_null_window_and_multi_identity(db_setup, monkeypatch):
    """NULL and 'primary' windows are ONE identity (coalesce); distinct
    windows and quota keys are separate identities, each keeping its latest."""
    now = utcnow()
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        await accounts_repo.upsert(_make_account("acc_multi", "multi@example.com"))
        # NULL window (legacy primary) older than the 'primary' row: same
        # identity, so only the newer 'primary' row survives.
        session.add(
            UsageHistory(account_id="acc_multi", window=None, used_percent=1.0, recorded_at=now - timedelta(days=200))
        )
        session.add(
            UsageHistory(
                account_id="acc_multi", window="primary", used_percent=2.0, recorded_at=now - timedelta(days=150)
            )
        )
        # Secondary window is its own identity; its single old row survives.
        session.add(
            UsageHistory(
                account_id="acc_multi", window="secondary", used_percent=3.0, recorded_at=now - timedelta(days=180)
            )
        )
        # Two quota keys: each keeps its own latest.
        for quota_key, percents in (("gpt-5-pro", (10.0, 11.0)), ("sora-video", (20.0, 21.0))):
            for offset, percent in enumerate(percents):
                session.add(
                    AdditionalUsageHistory(
                        account_id="acc_multi",
                        quota_key=quota_key,
                        limit_name=quota_key,
                        metered_feature=quota_key,
                        window="primary",
                        used_percent=percent,
                        recorded_at=now - timedelta(days=200 - offset * 10),
                    )
                )
        await session.commit()

    await _set_retention(usage_history=45)
    deleted = await run_retention_pass(now=now)
    assert deleted["usage_history"] == 1  # only the NULL-window row
    assert deleted["additional_usage_history"] == 2  # older row of each quota key

    async with SessionLocal() as session:
        usage_rows = (await session.execute(select(UsageHistory))).scalars().all()
        additional_rows = (await session.execute(select(AdditionalUsageHistory))).scalars().all()
    assert sorted((row.window, row.used_percent) for row in usage_rows) == [("primary", 2.0), ("secondary", 3.0)]
    assert sorted((row.quota_key, row.used_percent) for row in additional_rows) == [
        ("gpt-5-pro", 11.0),
        ("sora-video", 21.0),
    ]


@pytest.mark.asyncio
async def test_usage_history_backlog_drains_across_batches(db_setup, monkeypatch):
    now = utcnow()
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        await accounts_repo.upsert(_make_account("acc_ubatch", "ubatch@example.com"))
        for index in range(7):
            session.add(
                UsageHistory(
                    account_id="acc_ubatch",
                    window="primary",
                    used_percent=float(index),
                    recorded_at=now - timedelta(days=200 - index),
                )
            )
        await session.commit()

    await _set_retention(usage_history=45)
    monkeypatch.setattr(retention_job, "BATCH_SIZE", 2)
    deleted = await run_retention_pass(now=now)
    assert deleted["usage_history"] == 6  # all but the latest row

    async with SessionLocal() as session:
        rows = (await session.execute(select(UsageHistory))).scalars().all()
    assert len(rows) == 1
    assert rows[0].used_percent == 6.0


@pytest.mark.asyncio
async def test_api_key_totals_survive_pruning_and_match_pre_fold(db_setup, monkeypatch):
    """Per-key lifetime summaries fold alongside account sums; pruning folded
    rows must not change them, and folded totals must equal pre-fold ones."""
    from app.db.models import ApiKey, ApiKeyUsageRollup
    from app.modules.api_keys.repository import ApiKeysRepository

    now = utcnow()
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        logs_repo = RequestLogsRepository(session)
        await accounts_repo.upsert(_make_account("acc_key", "key@example.com"))
        session.add(ApiKey(id="key_ret", name="Retained", key_hash="hash_ret", key_prefix="sk-ret"))
        await session.commit()
        for index, days_ago in enumerate((60, 40, 1)):
            log = await logs_repo.add_log(
                account_id="acc_key",
                request_id=f"req_key_{index}",
                model="gpt-5.1-codex",
                input_tokens=100,
                output_tokens=50,
                latency_ms=100,
                status="success",
                error_code=None,
                requested_at=now - timedelta(days=days_ago),
                cost_usd=0.01,
                api_key_id="key_ret",
            )
            assert log is not None

    async def _key_summary():
        async with SessionLocal() as session:
            return await ApiKeysRepository(session).get_usage_summary_by_key_id("key_ret")

    before = await _key_summary()
    assert before.request_count == 3
    assert before.total_tokens == 3 * 150

    await run_fold_pass(now=now)
    await run_hourly_fold_pass(now=now)
    await run_conversation_fold_pass(now=now)
    await run_report_fold_pass(now=now)
    assert await _key_summary() == before

    await _set_retention(request_logs=30)
    deleted = await run_retention_pass(now=now)
    assert deleted["request_logs"] == 2
    assert await _key_summary() == before

    # Key deletion removes its rollup row.
    async with SessionLocal() as session:
        assert await ApiKeysRepository(session).delete("key_ret")
    async with SessionLocal() as session:
        assert (await session.execute(select(ApiKeyUsageRollup))).scalars().all() == []


def test_api_key_rollup_migration_resets_prior_fold_state(tmp_path):
    """Installs that folded account rollups before this migration must be
    reset (rollup rows + watermark together) so per-key totals re-backfill
    instead of collapsing to the live tail."""
    import sqlalchemy as sa
    from alembic import command

    from app.db.migrate import _build_alembic_config

    db_path = tmp_path / "mig-key-rollup.sqlite3"
    url = f"sqlite:///{db_path}"
    cfg = _build_alembic_config(url)

    command.upgrade(cfg, "20260712_010000_add_account_usage_rollups")

    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO accounts (id, email, plan_type, access_token_encrypted, refresh_token_encrypted,"
                " id_token_encrypted, last_refresh, status, codex_installation_id)"
                " VALUES ('acc_mig', 'mig@example.com', 'plus', X'00', X'00', X'00', '2026-01-01 00:00:00',"
                " 'active', 'inst_mig')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO account_usage_rollups (account_id, request_count, input_tokens, output_tokens,"
                " cached_input_tokens, total_cost_usd) VALUES ('acc_mig', 5, 100, 50, 0, 1.0)"
            )
        )
        conn.execute(sa.text("UPDATE account_usage_rollup_state SET folded_through = '2026-07-01 00:00:00'"))

    command.upgrade(cfg, "20260712_020000_add_api_key_usage_rollups")

    with engine.begin() as conn:
        rollups = conn.execute(sa.text("SELECT count(*) FROM account_usage_rollups")).scalar_one()
        watermark = conn.execute(sa.text("SELECT folded_through FROM account_usage_rollup_state")).scalar_one()
        key_rollups = conn.execute(sa.text("SELECT count(*) FROM api_key_usage_rollups")).scalar_one()
    engine.dispose()

    assert rollups == 0
    assert str(watermark).startswith("1970-01-01")
    assert key_rollups == 0


@pytest.mark.asyncio
async def test_fold_start_covers_key_only_soft_deleted_history(db_setup):
    """A soft-deleted row with an api_key_id is invisible to the account
    aggregate but still counts for per-key totals; the backfill start must
    not skip past it."""
    from datetime import timedelta as _td

    from app.db.models import ApiKey, ApiKeyUsageRollup
    from app.db.models import RequestLog as RequestLogModel

    now = utcnow()
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        logs_repo = RequestLogsRepository(session)
        await accounts_repo.upsert(_make_account("acc_keyonly", "keyonly@example.com"))
        session.add(ApiKey(id="key_only", name="KeyOnly", key_hash="hash_keyonly", key_prefix="sk-ko"))
        # Oldest row: soft-deleted (account detached) but key-attributed —
        # only the key aggregate counts it.
        session.add(
            RequestLogModel(
                account_id=None,
                api_key_id="key_only",
                request_id="req_keyonly_old",
                model="gpt-5.1-codex",
                status="success",
                input_tokens=100,
                output_tokens=50,
                requested_at=now - timedelta(days=40),
                deleted_at=now - timedelta(days=30),
            )
        )
        await session.commit()
        await _add_log(
            logs_repo, account_id="acc_keyonly", request_id="req_keyonly_new", requested_at=now - _td(days=2)
        )

    await run_fold_pass(now=now)

    async with SessionLocal() as session:
        key_rollup = (await session.execute(select(ApiKeyUsageRollup))).scalars().all()
    assert len(key_rollup) == 1
    assert key_rollup[0].request_count == 1  # the soft-deleted key row folded

    from app.modules.api_keys.repository import ApiKeysRepository

    async with SessionLocal() as session:
        summary = await ApiKeysRepository(session).get_usage_summary_by_key_id("key_only")
    assert summary.request_count == 1
    assert summary.total_tokens == 150


@pytest.mark.asyncio
async def test_dashboard_zero_disables_retention(db_setup):
    now = utcnow()
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        await accounts_repo.upsert(_make_account("acc_zero", "zero@example.com"))
        session.add(UsageHistory(account_id="acc_zero", used_percent=10.0, recorded_at=now - timedelta(days=400)))
        session.add(UsageHistory(account_id="acc_zero", used_percent=20.0, recorded_at=now - timedelta(days=390)))
        await session.commit()

    await _set_retention(request_logs=None, usage_history=0)

    deleted = await run_retention_pass(now=now)
    assert deleted == {"request_logs": 0, "usage_history": 0, "additional_usage_history": 0, "hourly_rollups": 0}
    async with SessionLocal() as session:
        assert len((await session.execute(select(UsageHistory.id))).scalars().all()) == 2


@pytest.mark.asyncio
async def test_null_dashboard_value_disables_retention_despite_removed_env_alias(db_setup, monkeypatch):
    """NULL dashboard values are disabled; the removed env alias has no effect."""
    now = utcnow()
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        await accounts_repo.upsert(_make_account("acc_env", "env@example.com"))
        session.add(UsageHistory(account_id="acc_env", used_percent=10.0, recorded_at=now - timedelta(days=400)))
        session.add(UsageHistory(account_id="acc_env", used_percent=20.0, recorded_at=now - timedelta(days=1)))
        await session.commit()

    # Force row creation so the dashboard columns exist and stay NULL.
    await _set_retention(request_logs=None, usage_history=None)
    monkeypatch.setenv("CODEX_LB_USAGE_HISTORY_RETENTION_DAYS", "45")

    retention = await retention_job.get_effective_retention()
    assert retention.enabled is False
    deleted = await run_retention_pass(now=now)
    assert deleted["usage_history"] == 0
    async with SessionLocal() as session:
        remaining = (await session.execute(select(UsageHistory.used_percent))).scalars().all()
<<<<<<< 22625a07e
    assert remaining == [20.0]


async def _set_dashboard_hourly_retention(days: int | None) -> None:
    """Store the dashboard hourly-rollup retention override and refresh the cache."""
    async with SessionLocal() as session:
        row = await SettingsRepository(session).get_or_create()
        row.hourly_rollup_retention_days = days
        await session.commit()
    await get_settings_cache().invalidate()


@pytest.mark.asyncio
async def test_hourly_rollup_retention_resolves_dashboard_first(db_setup, monkeypatch):
    """Dashboard-first precedence: a non-NULL dashboard value wins over the
    deprecated env alias (including an explicit dashboard 0 = disabled);
    while the dashboard value is unset the env alias applies."""
    monkeypatch.setenv("CODEX_LB_HOURLY_ROLLUP_RETENTION_DAYS", "30")
    get_settings.cache_clear()
    try:
        async with SessionLocal() as session:
            row = await SettingsRepository(session).get_or_create()
            assert row.hourly_rollup_retention_days is None
        assert (await get_effective_retention()).hourly_rollup_days == 30

        await _set_dashboard_hourly_retention(60)
        assert (await get_effective_retention()).hourly_rollup_days == 60

        await _set_dashboard_hourly_retention(0)
        assert (await get_effective_retention()).hourly_rollup_days == 0
    finally:
        await _set_dashboard_hourly_retention(None)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_hourly_rollup_pruning_prunes_only_past_dashboard_window(db_setup, monkeypatch):
    """With raw retention at 30d and the dashboard window at 45d, an hourly
    bucket at 100d is pruned while the 40d and 10d buckets survive, and the
    pruned range remains queryable from the daily lifetime store. (Hourly
    pruning only runs while request-log retention is enabled — with raw
    retention disabled the hourly store is kept at full precision.)"""
    now = utcnow()
    _set_retention(monkeypatch, request_logs=30)
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        logs_repo = RequestLogsRepository(session)
        await accounts_repo.upsert(_make_account("acc_hrp", "hrp@example.com"))
        for days, request_id in ((100, "req_hrp_100"), (40, "req_hrp_40"), (10, "req_hrp_10")):
            await _add_log(
                logs_repo, account_id="acc_hrp", request_id=request_id, requested_at=now - timedelta(days=days)
            )

    await run_fold_pass(now=now)
    await run_hourly_fold_pass(now=now)
    await run_conversation_fold_pass(now=now)
    await run_daily_fold_pass()

    async with SessionLocal() as session:
        state = (await session.execute(select(AccountUsageRollupState))).scalar_one()
        assert state.daily_folded_through is not None

    await _set_dashboard_hourly_retention(45)
    try:
        deleted = await run_retention_pass(now=now)
        assert deleted["hourly_rollups"] > 0

        async with SessionLocal() as session:
            hourly = (
                (
                    await session.execute(
                        select(RequestUsageHourlyRollup.request_count).order_by(RequestUsageHourlyRollup.bucket_epoch)
                    )
                )
                .scalars()
                .all()
            )
            daily_rows = (await session.execute(select(RequestUsageDailyRollup.request_count))).scalars().all()
        # The 100d bucket left hourly; the newer buckets survive.
        assert sum(hourly) == 2
        # The daily lifetime store is untouched: all three days remain.
        assert sum(daily_rows) == 3

        # Idempotent: a second pass finds nothing more to prune.
        assert (await run_retention_pass(now=now))["hourly_rollups"] == 0
    finally:
        await _set_dashboard_hourly_retention(None)


@pytest.mark.asyncio
async def test_hourly_rollup_pruning_never_cuts_below_raw_window(db_setup, monkeypatch):
    """With raw retention at 30d and a dashboard hourly window of 10d, the
    effective hourly window is max(10, 30) = 30: a 20d-old bucket survives."""
    now = utcnow()
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        logs_repo = RequestLogsRepository(session)
        await accounts_repo.upsert(_make_account("acc_hrr", "hrr@example.com"))
        await _add_log(logs_repo, account_id="acc_hrr", request_id="req_hrr_20", requested_at=now - timedelta(days=20))

    await run_fold_pass(now=now)
    await run_hourly_fold_pass(now=now)
    await run_conversation_fold_pass(now=now)
    await run_daily_fold_pass()

    _set_retention(monkeypatch, request_logs=30)
    await _set_dashboard_hourly_retention(10)
    try:
        deleted = await run_retention_pass(now=now)
        assert deleted == {"request_logs": 0, "usage_history": 0, "additional_usage_history": 0, "hourly_rollups": 0}
        async with SessionLocal() as session:
            assert (await session.execute(select(RequestUsageHourlyRollup.request_count))).scalars().all() == [1]
    finally:
        await _set_dashboard_hourly_retention(None)


@pytest.mark.asyncio
async def test_hourly_rollup_pruning_skipped_while_raw_retention_disabled(db_setup, monkeypatch):
    """F3: with raw retention disabled (0 = unlimited) hourly pruning is
    skipped entirely, even with an hourly window set. The rollup-served
    history reads label their local days from the hourly table wherever the
    UTC offset is non-zero, so pruning hours raw keeps would leave days
    raw cannot recompute; the hourly table is tiny next to unlimited raw
    and simply stays permanent."""
    now = utcnow()
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        logs_repo = RequestLogsRepository(session)
        await accounts_repo.upsert(_make_account("acc_hrz", "hrz@example.com"))
        await _add_log(
            logs_repo, account_id="acc_hrz", request_id="req_hrz_100", requested_at=now - timedelta(days=100)
        )

    await run_fold_pass(now=now)
    await run_hourly_fold_pass(now=now)
    await run_conversation_fold_pass(now=now)
    await run_daily_fold_pass()

    _set_retention(monkeypatch, request_logs=0)
    await _set_dashboard_hourly_retention(10)
    try:
        deleted = await run_retention_pass(now=now)
        assert deleted == {"request_logs": 0, "usage_history": 0, "additional_usage_history": 0, "hourly_rollups": 0}
        async with SessionLocal() as session:
            assert (await session.execute(select(RequestUsageHourlyRollup.request_count))).scalars().all() == [1]
        # Idempotent: the gate keeps the pass a no-op.
        assert (await run_retention_pass(now=now))["hourly_rollups"] == 0
    finally:
        await _set_dashboard_hourly_retention(None)
||||||| 84fde5a1e
    assert remaining == [20.0]
=======
    assert sorted(remaining) == [10.0, 20.0]
>>>>>>> 72630bbfe
