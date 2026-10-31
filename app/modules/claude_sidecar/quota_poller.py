from __future__ import annotations

import asyncio
import contextlib
import importlib
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Protocol, cast

from app.core.clients.claude_sidecar import (
    ClaudeSidecarClient,
    ClaudeSidecarError,
    ClaudeSidecarUnavailableError,
)
from app.core.config.settings import get_settings
from app.core.config.settings_cache import get_settings_cache
from app.core.types import JsonValue
from app.db.session import get_background_session
from app.modules.claude_sidecar.capacity_hold import next_hold_release
from app.modules.claude_sidecar.excluded_models import excluded_models_from_auth_file
from app.modules.claude_sidecar.exclusion_lock import exclusion_write_lock
from app.modules.claude_sidecar.grok_credits import (
    GrokCreditsError,
    GrokCreditsQuota,
    GrokCreditsRateLimit,
    XaiUsageObservation,
    fetch_grok_credits,
    grok_credential_usable,
    project_xai_usage,
    restore_xai_usage_observations,
    strip_observed_limits,
    take_xai_usage_observations,
)
from app.modules.claude_sidecar.oauth_usage import (
    ClaudeOAuthUsageError,
    fetch_claude_oauth_usage,
)
from app.modules.claude_sidecar.quota import (
    SidecarAuthQuota,
    SidecarOAuthUsage,
    SidecarQuotaSnapshot,
    SidecarQuotaStatus,
    credential_provider,
    parse_auth_files,
    snapshot_from_json,
    snapshot_to_json,
)
from app.modules.claude_sidecar.rate_limit_hold import (
    apply_hold_results,
    plan_rate_limit_holds,
    plan_xai_rate_limit_holds,
)
from app.modules.claude_sidecar.session_affinity_guard import check_cliproxy_session_affinity
from app.modules.proxy.claude_sidecar_dispatch import sidecar_config_from_settings
from app.modules.settings.repository import SettingsRepository

logger = logging.getLogger(__name__)

# How long after a hold's release instant the poller runs, so the usage API
# already reports the reset window as renewed.
_HOLD_RELEASE_POLL_DELAY_SECONDS = 1.0
# How many Grok credit fetches one poll runs at once.
_GROK_CREDITS_CONCURRENCY = 4


class _LeaderElectionLike(Protocol):
    async def try_acquire(self) -> bool: ...


def _get_leader_election() -> _LeaderElectionLike:
    module = importlib.import_module("app.core.scheduling.leader_election")
    return cast(_LeaderElectionLike, module.get_leader_election())


@dataclass(slots=True)
class ClaudeSidecarQuotaPoller:
    """Polls CLIProxyAPI's management auth-files endpoint and stores the snapshot."""

    interval_seconds: float
    enabled: bool
    _task: asyncio.Task[None] | None = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _client_factory: type[ClaudeSidecarClient] = ClaudeSidecarClient

    async def start(self) -> None:
        if not self.enabled:
            return
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            await self._poll_once()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=await self._next_wait_seconds())
            except asyncio.TimeoutError:
                continue

    async def _next_wait_seconds(self) -> float:
        """Sleep the poll interval, but wake just after the next hold release.

        A held auth is enabled again by a poll. Waiting the full interval past
        its reset would keep requests on 429 (or waiting) for up to that long
        after capacity is back.
        """
        try:
            settings_row = await get_settings_cache().get()
        except Exception:
            return self.interval_seconds
        release = next_hold_release(
            snapshot_from_json(settings_row.claude_sidecar_quota_state_json),
            datetime.now(timezone.utc),
        )
        if release is None:
            return self.interval_seconds
        until_release = (release - datetime.now(timezone.utc)).total_seconds() + _HOLD_RELEASE_POLL_DELAY_SECONDS
        return max(_HOLD_RELEASE_POLL_DELAY_SECONDS, min(self.interval_seconds, until_release))

    async def _poll_once(self) -> None:
        try:
            if not await _get_leader_election().try_acquire():
                return
            async with self._lock:
                await self._poll_locked()
        except Exception:
            logger.warning("Claude sidecar quota poll loop encountered unexpected error", exc_info=True)

    async def _poll_locked(self) -> None:
        try:
            settings_row = await get_settings_cache().get()
        except Exception:
            logger.warning("failed to load dashboard settings for Claude sidecar quota poll", exc_info=True)
            return

        if not settings_row.claude_sidecar_enabled:
            return
        if not settings_row.claude_sidecar_management_key_encrypted:
            return

        config = sidecar_config_from_settings(settings_row)
        if not config.management_key:
            return
        client = self._client_factory(config)
        await check_cliproxy_session_affinity(client)
        stored_before = snapshot_from_json(settings_row.claude_sidecar_quota_state_json)
        snapshot = await _classify_poll_result(client, stored_before)
        if snapshot.status == "healthy":
            observations = take_xai_usage_observations()
            snapshot = project_xai_usage(snapshot, observations)
        else:
            observations = ()
        await self._persist_snapshot(
            client,
            snapshot,
            stored_before=stored_before,
            restore_observations=observations,
        )

    async def _persist_snapshot(
        self,
        client: ClaudeSidecarClient,
        snapshot: SidecarQuotaSnapshot,
        *,
        stored_before: SidecarQuotaSnapshot | None = None,
        restore_observations: tuple[XaiUsageObservation, ...] = (),
    ) -> None:
        try:
            async with exclusion_write_lock(), get_background_session() as session:
                repo = SettingsRepository(session)
                previous = snapshot_from_json((await repo.get_fresh()).claude_sidecar_quota_state_json)
                snapshot = await _apply_rate_limit_holds(
                    client,
                    snapshot,
                    previous,
                    stored_before=stored_before,
                )
                snapshot = await asyncio.to_thread(_refresh_exclusions, snapshot)
                await repo.update_operational(
                    claude_sidecar_quota_state_json=snapshot_to_json(snapshot),
                    claude_sidecar_quota_checked_at=snapshot.checked_at,
                )
            await get_settings_cache().invalidate()
        except Exception:
            restore_xai_usage_observations(restore_observations)
            logger.warning("failed to persist Claude sidecar quota snapshot", exc_info=True)


async def _apply_rate_limit_holds(
    client: ClaudeSidecarClient,
    snapshot: SidecarQuotaSnapshot,
    previous: SidecarQuotaSnapshot | None,
    *,
    stored_before: SidecarQuotaSnapshot | None = None,
) -> SidecarQuotaSnapshot:
    """Disable an exhausted auth until its known reset, then enable it again.

    Unhealthy polls, and a failed auth listing under the write lock, keep the
    holds already stored. A failed listing keeps the first listing's ``disabled``
    flags, except for auths whose stored flag changed during the usage fetch.
    Those auths take the snapshot read under the lock. A failed management
    update leaves that one transition uncommitted. ``disabled`` used for planning
    comes from the auth listing taken under the lock when that listing succeeds.
    """
    previous_holds = previous.rate_limit_holds if previous is not None else ()
    if snapshot.status != "healthy":
        return replace(snapshot, rate_limit_holds=previous_holds)

    live_disabled = await _live_disabled_by_name(client)
    if live_disabled is None:
        changed = _changed_disabled_flags(stored_before, previous)
        accounts = _accounts_with_live_disabled(snapshot.accounts, changed) if changed else snapshot.accounts
        return replace(snapshot, accounts=accounts, rate_limit_holds=previous_holds)
    accounts = _accounts_with_live_disabled(snapshot.accounts, live_disabled)
    plan = plan_rate_limit_holds(accounts, previous_holds, snapshot.checked_at)
    failed_disables: set[str] = set()
    failed_enables: set[str] = set()
    for name in plan.disable_names:
        if not await _patch_auth_disabled(client, name, True):
            failed_disables.add(name)
    for name in plan.enable_names:
        if not await _patch_auth_disabled(client, name, False):
            failed_enables.add(name)
    accounts, holds = apply_hold_results(
        accounts,
        previous_holds,
        plan,
        failed_disables=failed_disables,
        failed_enables=failed_enables,
    )
    xai_plan = plan_xai_rate_limit_holds(accounts, holds, snapshot.checked_at)
    xai_failed_disables: set[str] = set()
    xai_failed_enables: set[str] = set()
    for name in xai_plan.disable_names:
        if not await _patch_auth_disabled(client, name, True):
            xai_failed_disables.add(name)
    for name in xai_plan.enable_names:
        if not await _patch_auth_disabled(client, name, False):
            xai_failed_enables.add(name)
    accounts, holds = apply_hold_results(
        accounts,
        holds,
        xai_plan,
        failed_disables=xai_failed_disables,
        failed_enables=xai_failed_enables,
        provider="xai",
    )
    return replace(snapshot, accounts=strip_observed_limits(accounts), rate_limit_holds=holds)


async def _live_disabled_by_name(client: ClaudeSidecarClient) -> dict[str, bool] | None:
    """Re-list auth files under the write lock and return each live ``disabled`` flag.

    Pause and Resume hold the same lock across their management PATCH, so this
    listing already includes that change. A listing error returns None. The
    caller then keeps the stored holds and the first listing's ``disabled``
    flags, except where a pause or resume changed the stored snapshot during
    the usage fetch.
    """
    try:
        raw_files = await client.list_auth_files()
    except ClaudeSidecarError:
        logger.warning("failed to re-list CLIProxyAPI auth files for a rate-limit hold", exc_info=True)
        return None
    parsed = await asyncio.to_thread(_polled_accounts, raw_files)
    return {account.name: account.disabled for account in parsed if account.name}


def _disabled_flags(snapshot: SidecarQuotaSnapshot | None) -> dict[str, bool]:
    """Return each named auth's ``disabled`` flag from a stored snapshot."""

    if snapshot is None:
        return {}
    return {auth.name: auth.disabled for auth in snapshot.accounts if auth.name}


def _changed_disabled_flags(
    before: SidecarQuotaSnapshot | None,
    after: SidecarQuotaSnapshot | None,
) -> dict[str, bool]:
    """Return ``disabled`` flags that changed while the usage fetch was in flight."""

    before_flags = _disabled_flags(before)
    after_flags = _disabled_flags(after)
    return {name: disabled for name, disabled in after_flags.items() if before_flags.get(name) != disabled}


def _accounts_with_live_disabled(
    accounts: tuple[SidecarAuthQuota, ...],
    live_disabled: dict[str, bool],
) -> tuple[SidecarAuthQuota, ...]:
    """Replace ``disabled`` with the value from the locked auth listing.

    The first listing is taken before the write lock. Names present in the
    supplied map take that value. Names absent from it keep the value from the
    first listing.
    """
    return tuple(
        replace(account, disabled=live_disabled[account.name]) if account.name in live_disabled else account
        for account in accounts
    )


async def _patch_auth_disabled(client: ClaudeSidecarClient, name: str, disabled: bool) -> bool:
    try:
        await client.patch_auth_file_disabled(name, disabled)
    except ClaudeSidecarError:
        logger.warning(
            "failed to set CLIProxyAPI auth %s disabled=%s for a rate-limit hold",
            name,
            disabled,
            exc_info=True,
        )
        return False
    return True


def _refresh_exclusions(snapshot: SidecarQuotaSnapshot) -> SidecarQuotaSnapshot:
    accounts = []
    for auth in snapshot.accounts:
        patterns = excluded_models_from_auth_file(auth.credential_path)
        accounts.append(
            replace(
                auth,
                excluded_models=tuple(patterns or ()),
                excluded_models_available=patterns is not None,
            )
        )
    return replace(snapshot, accounts=tuple(accounts))


async def _classify_poll_result(
    client: ClaudeSidecarClient,
    previous_snapshot: SidecarQuotaSnapshot | None = None,
) -> SidecarQuotaSnapshot:
    now = datetime.now(timezone.utc)
    try:
        raw_files = await client.list_auth_files()
    except ClaudeSidecarError as exc:
        if exc.status_code in (401, 403):
            return _failed_poll_snapshot(now, "unauthorized", exc.message, previous_snapshot)
        if isinstance(exc, ClaudeSidecarUnavailableError):
            return _failed_poll_snapshot(now, "unreachable", exc.message, previous_snapshot)
        return _failed_poll_snapshot(now, "error", exc.message, previous_snapshot)
    except Exception as exc:
        return _failed_poll_snapshot(now, "error", str(exc) or exc.__class__.__name__, previous_snapshot)

    parsed = await asyncio.to_thread(_polled_accounts, raw_files)
    accounts = await _attach_oauth_usage(client, parsed, previous_snapshot)
    accounts = await _attach_grok_credits(client, accounts, previous_snapshot)
    return SidecarQuotaSnapshot(
        checked_at=now,
        status="healthy",
        message=None,
        accounts=tuple(accounts),
    )


def _failed_poll_snapshot(
    checked_at: datetime,
    status: SidecarQuotaStatus,
    message: str,
    previous: SidecarQuotaSnapshot | None,
) -> SidecarQuotaSnapshot:
    """Record a failed management read without forgetting the last good accounts.

    A 401, 403, timeout, or 5xx from CLIProxyAPI's management API does not mean
    the credentials stopped serving. Dropping them makes capacity routing refuse
    Claude traffic that CLIProxyAPI can still handle. The status and message say
    the read failed; the accounts and holds stay until a healthy poll replaces them.
    """

    accounts = previous.accounts if previous is not None else ()
    holds = previous.rate_limit_holds if previous is not None else ()
    return SidecarQuotaSnapshot(
        checked_at=checked_at,
        status=status,
        message=message,
        accounts=accounts,
        rate_limit_holds=holds,
    )


async def _attach_oauth_usage(
    client: ClaudeSidecarClient,
    accounts: list[SidecarAuthQuota],
    previous_snapshot: SidecarQuotaSnapshot | None = None,
) -> list[SidecarAuthQuota]:
    previous_usage = _previous_oauth_usage_by_key(previous_snapshot)
    enriched: list[SidecarAuthQuota] = []
    for account in accounts:
        if credential_provider(account.provider) != "claude":
            enriched.append(account)
            continue
        usage = None
        if account.auth_index:
            try:
                usage = await fetch_claude_oauth_usage(client, account.auth_index)
            except ClaudeOAuthUsageError as exc:
                logger.debug(
                    "failed to fetch Claude OAuth usage for %s: %s",
                    account.email or account.auth_index or account.name,
                    exc,
                )
        if usage is None:
            # Anthropic's OAuth usage endpoint intermittently rate-limits
            # (HTTP 429); keep the last-known buckets so the dashboard's
            # 5h/weekly bars do not flap to "Unavailable" between polls.
            usage = previous_usage.get(_auth_identity_key(account))
        enriched.append(replace(account, oauth_usage=usage))
    return enriched


def _previous_oauth_usage_by_key(
    snapshot: SidecarQuotaSnapshot | None,
) -> dict[str | None, SidecarOAuthUsage]:
    if snapshot is None:
        return {}
    usage_by_key: dict[str | None, SidecarOAuthUsage] = {}
    for account in snapshot.accounts:
        key = _auth_identity_key(account)
        if key is not None and account.oauth_usage is not None:
            usage_by_key[key] = account.oauth_usage
    return usage_by_key


async def _attach_grok_credits(
    client: ClaudeSidecarClient,
    accounts: list[SidecarAuthQuota],
    previous_snapshot: SidecarQuotaSnapshot | None,
) -> list[SidecarAuthQuota]:
    """Fetch GetGrokCreditsConfig for each xAI credential.

    A 429 becomes this poll's ``observed_limit``. Any other failure, including
    a timeout, keeps the last stored windows. Claude accounts are copied
    through. Fetches run a few at a time, so a stalled login delays the poll by
    about one fetch timeout, not one per xAI login.
    """

    previous_credits = _previous_grok_credits_by_key(previous_snapshot)
    limit = asyncio.Semaphore(_GROK_CREDITS_CONCURRENCY)

    async def enrich(account: SidecarAuthQuota) -> SidecarAuthQuota:
        if credential_provider(account.provider) != "xai" or not account.auth_index:
            return account
        stored = previous_credits.get(_auth_identity_key(account))
        if not grok_credential_usable(account):
            return replace(account, grok_credits=stored) if stored is not None else account
        try:
            async with limit:
                credits = await fetch_grok_credits(
                    client,
                    account.auth_index,
                    credential_usable=True,
                )
        except GrokCreditsRateLimit as exc:
            base = stored or GrokCreditsQuota()
            return replace(account, grok_credits=replace(base, observed_limit=exc.kind))
        except GrokCreditsError as exc:
            logger.debug(
                "failed to fetch Grok credits for %s: %s",
                account.email or account.auth_index or account.name,
                exc,
            )
            return replace(account, grok_credits=stored) if stored is not None else account
        if stored is not None and stored.token_rollup is not None:
            credits = replace(credits, token_rollup=stored.token_rollup)
        return replace(account, grok_credits=credits)

    return list(await asyncio.gather(*(enrich(account) for account in accounts)))


def _previous_grok_credits_by_key(
    snapshot: SidecarQuotaSnapshot | None,
) -> dict[str | None, GrokCreditsQuota]:
    if snapshot is None:
        return {}
    credits_by_key: dict[str | None, GrokCreditsQuota] = {}
    for account in snapshot.accounts:
        key = _auth_identity_key(account)
        if key is not None and account.grok_credits is not None:
            credits_by_key[key] = account.grok_credits
    return credits_by_key


def _polled_accounts(raw_files: Iterable[Mapping[str, JsonValue]]) -> list[SidecarAuthQuota]:
    """Parse the auth listing the poller is allowed to manage.

    Claude credentials come first, then xAI credentials. Other providers are
    left out.
    """

    entries = list(raw_files)
    return parse_auth_files(entries, provider="claude") + parse_auth_files(entries, provider="xai")


def _auth_identity_key(account: SidecarAuthQuota) -> str | None:
    if account.auth_index:
        return f"auth:{account.auth_index}"
    if account.email:
        return f"email:{account.email.lower()}"
    if account.name:
        return f"name:{account.name.lower()}"
    return None


def build_claude_sidecar_quota_poller() -> ClaudeSidecarQuotaPoller:
    settings = get_settings()
    interval = max(1.0, float(settings.claude_sidecar_quota_poll_interval_seconds))
    # Scheduler is always started; the per-poll gate ensures we no-op until the
    # operator configures both the sidecar and a Management API key.
    return ClaudeSidecarQuotaPoller(
        interval_seconds=interval,
        enabled=True,
    )
