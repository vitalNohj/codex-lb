"""Build the quota feed from the same inputs the router selects on.

Codex rows come from :func:`app.modules.proxy.load_balancer._build_states`.
CLIProxyAPI rows come from :func:`account_state_for_auth`. The pool switch
stays off; stored sidecar snapshots are still reported.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.balancer import ERROR_BACKOFF_THRESHOLD, AccountState
from app.core.config.settings_cache import get_settings_cache
from app.db.models import Account, AccountStatus, UsageHistory
from app.modules.accounts.repository import AccountsRepository
from app.modules.claude_sidecar.capacity_hold import StoredSnapshotReader
from app.modules.claude_sidecar.quota import (
    GrokCreditWindow,
    SidecarAuthQuota,
    SidecarRateLimitHold,
    credential_provider,
)
from app.modules.cliproxy_accounts.repository import CliproxyCredentialPrefixRepository
from app.modules.proxy.cliproxy_account_routing import _prefix_for_auth, _xai_window, account_state_for_auth
from app.modules.proxy.load_balancer import _build_states, _select_long_window_entry
from app.modules.quota_feed.schemas import (
    ProviderHeadroom,
    QuotaConfidence,
    QuotaFeedAccount,
    QuotaFeedResponse,
    QuotaFeedWindow,
)
from app.modules.usage.repository import UsageRepository

_KNOWN_PROVIDERS = frozenset({"codex", "claude", "xai"})
_BLOCKED_STATUSES = frozenset(
    {
        AccountStatus.RATE_LIMITED,
        AccountStatus.QUOTA_EXCEEDED,
        AccountStatus.PAUSED,
        AccountStatus.REAUTH_REQUIRED,
        AccountStatus.DEACTIVATED,
    }
)
_OAUTH_SOURCE = {"claude": "anthropic_oauth_usage", "codex": "codex_oauth_usage"}
# Used only so a credential without a routable prefix still produces the
# quota fields ``account_state_for_auth`` would produce once a prefix exists.
# The stand-in is not returned.
_STATE_PREFIX = "feed"


@dataclass(frozen=True, slots=True)
class QuotaFeedScope:
    """Which pool rows this caller may see.

    ``codex_account_ids is None`` means every Codex account. A scoped proxy
    key passes the ids assigned to that key. Sidecar rows are pool-wide:
    those credentials are not assigned per key, and every authenticated
    caller that can send sidecar traffic can read their headroom.
    """

    codex_account_ids: frozenset[str] | None
    include_sidecar: bool


class QuotaFeedService:
    def __init__(
        self,
        accounts: AccountsRepository,
        usage: UsageRepository,
        prefixes: CliproxyCredentialPrefixRepository,
    ) -> None:
        self._accounts = accounts
        self._usage = usage
        self._prefixes = prefixes

    async def build(self, scope: QuotaFeedScope) -> QuotaFeedResponse:
        now = datetime.now(timezone.utc)
        accounts = await self._accounts.list_accounts()
        if scope.codex_account_ids is not None:
            accounts = [account for account in accounts if account.id in scope.codex_account_ids]
        account_ids = None if scope.codex_account_ids is None else [account.id for account in accounts]
        latest_primary = await self._usage.latest_by_account(account_ids=account_ids)
        latest_secondary = await self._usage.latest_by_account(window="secondary", account_ids=account_ids)
        latest_monthly = await self._usage.latest_by_account(window="monthly", account_ids=account_ids)
        states, _account_map = _build_states(
            accounts=accounts,
            latest_primary=latest_primary,
            latest_secondary=latest_secondary,
            latest_monthly=latest_monthly,
            runtime={},
        )
        long_window_ids = {
            account.id: _long_window_id(
                account,
                latest_monthly.get(account.id),
                latest_secondary.get(account.id),
            )
            for account in accounts
        }
        sidecar_accounts: Sequence[SidecarAuthQuota] = ()
        holds: Sequence[SidecarRateLimitHold] = ()
        prefixes_by_name: dict[str, str] = {}
        prefixes_by_index: dict[str, str] = {}
        if scope.include_sidecar:
            settings = await get_settings_cache().get()
            snapshot = StoredSnapshotReader().read(settings.claude_sidecar_quota_state_json)
            if snapshot is not None:
                sidecar_accounts = snapshot.accounts
                holds = snapshot.rate_limit_holds
            prefix_rows = await self._prefixes.list_all()
            prefixes_by_name = {row.credential_name: row.prefix for row in prefix_rows}
            prefixes_by_index = {row.auth_index: row.prefix for row in prefix_rows if row.auth_index}
        return compose_quota_feed(
            generated_at=now,
            codex_states=states,
            codex_long_window_ids=long_window_ids,
            sidecar_accounts=sidecar_accounts,
            holds=holds,
            prefixes_by_name=prefixes_by_name,
            prefixes_by_index=prefixes_by_index,
            now=now,
        )


def routing_state_for_auth(
    auth: SidecarAuthQuota,
    *,
    holds: Sequence[SidecarRateLimitHold],
    prefixes_by_name: Mapping[str, str],
    prefixes_by_index: Mapping[str, str],
    now: datetime,
) -> AccountState | None:
    """The ``AccountState`` the selector would build for this credential."""

    prefix = _prefix_for_auth(auth, dict(prefixes_by_name), dict(prefixes_by_index)) or _STATE_PREFIX
    return account_state_for_auth(auth, holds=holds, prefix=prefix, now=now)


def compose_quota_feed(
    *,
    generated_at: datetime,
    codex_states: Sequence[AccountState],
    codex_long_window_ids: Mapping[str, str],
    sidecar_accounts: Sequence[SidecarAuthQuota],
    holds: Sequence[SidecarRateLimitHold],
    prefixes_by_name: Mapping[str, str],
    prefixes_by_index: Mapping[str, str],
    now: datetime,
) -> QuotaFeedResponse:
    rows: list[tuple[AccountState, QuotaFeedAccount]] = [
        _codex_row(state, codex_long_window_ids.get(state.account_id, "seven_day")) for state in codex_states
    ]
    for auth in sidecar_accounts:
        state = routing_state_for_auth(
            auth,
            holds=holds,
            prefixes_by_name=prefixes_by_name,
            prefixes_by_index=prefixes_by_index,
            now=now,
        )
        if state is None:
            continue
        rows.append(_sidecar_row(auth, state))
    rows.sort(key=lambda item: (item[1].provider, item[1].account_key))
    grouped: dict[str, list[tuple[AccountState, QuotaFeedAccount]]] = defaultdict(list)
    for state, account in rows:
        grouped[account.provider].append((state, account))
    now_epoch = now.timestamp()
    return QuotaFeedResponse(
        schema_version=1,
        generated_at=generated_at,
        providers=[account for _state, account in rows],
        per_provider={provider: _headroom(grouped[provider], now_epoch) for provider in sorted(grouped)},
    )


def _codex_row(state: AccountState, long_window_id: str) -> tuple[AccountState, QuotaFeedAccount]:
    return (
        state,
        QuotaFeedAccount(
            provider="codex",
            account_key=state.account_id,
            windows=[
                QuotaFeedWindow(
                    id="five_hour",
                    kind="rolling",
                    percent_remaining=_remaining(state.used_percent),
                    resets_at=_epoch_datetime(state.primary_reset_at),
                    confidence=_confidence(state.used_percent, estimated=False),
                    source="codex_usage",
                ),
                QuotaFeedWindow(
                    id=long_window_id,
                    kind="monthly" if long_window_id == "monthly" else "rolling",
                    percent_remaining=_remaining(state.secondary_used_percent),
                    resets_at=_epoch_datetime(state.secondary_reset_at),
                    confidence=_confidence(state.secondary_used_percent, estimated=False),
                    source="codex_usage",
                ),
            ],
        ),
    )


def _sidecar_row(auth: SidecarAuthQuota, state: AccountState) -> tuple[AccountState, QuotaFeedAccount]:
    provider = credential_provider(auth.provider)
    feed_provider = provider if provider in _KNOWN_PROVIDERS else "unknown"
    if provider == "xai":
        windows = _xai_windows(auth, state)
    elif provider in _OAUTH_SOURCE:
        windows = _oauth_windows(state, source=_OAUTH_SOURCE[provider])
    else:
        estimated = state.status == AccountStatus.RATE_LIMITED
        windows = [
            QuotaFeedWindow(
                id="quota",
                kind="unknown",
                percent_remaining=_remaining(state.used_percent),
                resets_at=_epoch_datetime(state.reset_at),
                confidence=_confidence(state.used_percent, estimated=estimated),
                source="unknown",
            )
        ]
    return (
        state,
        QuotaFeedAccount(provider=feed_provider, account_key=state.account_id, windows=windows),
    )


def _oauth_windows(state: AccountState, *, source: str) -> list[QuotaFeedWindow]:
    estimated = state.status == AccountStatus.RATE_LIMITED
    return [
        QuotaFeedWindow(
            id="five_hour",
            kind="rolling",
            percent_remaining=_remaining(state.used_percent),
            resets_at=_epoch_datetime(state.reset_at),
            confidence=_confidence(state.used_percent, estimated=estimated),
            source=source,
        ),
        QuotaFeedWindow(
            id="seven_day",
            kind="rolling",
            percent_remaining=_remaining(state.secondary_used_percent),
            resets_at=_epoch_datetime(state.secondary_reset_at),
            confidence=_confidence(state.secondary_used_percent, estimated=False),
            source=source,
        ),
    ]


def _xai_windows(auth: SidecarAuthQuota, state: AccountState) -> list[QuotaFeedWindow]:
    credits = auth.grok_credits
    routing = _xai_window(credits)
    windows: list[QuotaFeedWindow] = []
    if credits is not None and credits.windows:
        for window in credits.windows:
            windows.append(_xai_credit_window(window, routing, state))
    else:
        estimated = state.status == AccountStatus.RATE_LIMITED
        windows.append(
            QuotaFeedWindow(
                id="credits",
                kind="credits",
                percent_remaining=_remaining(state.used_percent),
                resets_at=_epoch_datetime(state.reset_at),
                confidence=_confidence(state.used_percent, estimated=estimated),
                source="grok_credits_config",
            )
        )
    rollup = None if credits is None else credits.token_rollup
    has_tokens = rollup is not None and (rollup.total_tokens > 0 or rollup.request_count > 0)
    windows.append(
        QuotaFeedWindow(
            id="tokens_24h",
            kind="rolling",
            percent_remaining=None,
            resets_at=None,
            confidence="estimated" if has_tokens else "unknown",
            source="usage_queue_tokens",
        )
    )
    return windows


def _xai_credit_window(
    window: GrokCreditWindow,
    routing: GrokCreditWindow | None,
    state: AccountState,
) -> QuotaFeedWindow:
    is_routing = (
        routing is not None
        and window.id == routing.id
        and window.kind == routing.kind
        and window.percent_used == routing.percent_used
    )
    if is_routing and state.used_percent is not None:
        estimated = state.status == AccountStatus.RATE_LIMITED
        return QuotaFeedWindow(
            id=window.id,
            kind=window.kind,
            percent_remaining=_remaining(state.used_percent),
            resets_at=_epoch_datetime(state.reset_at) or _as_utc(window.resets_at),
            confidence=_confidence(state.used_percent, estimated=estimated),
            source="grok_credits_config",
        )
    remaining = window.percent_remaining
    return QuotaFeedWindow(
        id=window.id,
        kind=window.kind,
        percent_remaining=remaining,
        resets_at=_as_utc(window.resets_at),
        confidence="established" if remaining is not None else "unknown",
        source="grok_credits_config",
    )


def _headroom(
    rows: Sequence[tuple[AccountState, QuotaFeedAccount]],
    now_epoch: float,
) -> ProviderHeadroom:
    available = 0
    remainings: list[float] = []
    for state, _account in rows:
        if not _admitted(state, now_epoch):
            continue
        available += 1
        usable = _usable_remaining(state)
        if usable is not None:
            remainings.append(usable)
    return ProviderHeadroom(
        accounts_available=available,
        max_headroom_percent=max(remainings) if remainings else None,
    )


def _usable_remaining(state: AccountState) -> float | None:
    """Tightest window the selector actually scores.

    ``used_percent`` and ``secondary_used_percent`` are the binding inputs.
    Extra displayed windows, such as a non-routing xAI product bucket, do not
    change whether the account can serve traffic.
    """

    known = [
        remaining
        for remaining in (_remaining(state.used_percent), _remaining(state.secondary_used_percent))
        if remaining is not None
    ]
    if not known:
        return None
    return min(known)


def _admitted(state: AccountState, now_epoch: float) -> bool:
    """Hard filters from ``select_account`` before it mutates elapsed holds.

    A rate-limited row whose reset has already passed stays unavailable here.
    The selector clears that row only while choosing an account; the feed
    reports the stored inputs instead of that mutation.
    """

    if state.status in _BLOCKED_STATUSES:
        return False
    if state.cooldown_until is not None and state.cooldown_until > now_epoch:
        return False
    if state.error_count >= ERROR_BACKOFF_THRESHOLD and state.last_error_at is not None:
        backoff = min(300, 30 * (2 ** (state.error_count - ERROR_BACKOFF_THRESHOLD)))
        if now_epoch - state.last_error_at < backoff:
            return False
    return True


def _long_window_id(
    account: Account,
    monthly: UsageHistory | None,
    secondary: UsageHistory | None,
) -> str:
    selected = _select_long_window_entry(
        account=account,
        monthly_entry=monthly,
        secondary_entry=secondary,
    )
    if selected is not None and selected.window == "monthly":
        return "monthly"
    return "seven_day"


def _remaining(used_percent: float | None) -> float | None:
    if used_percent is None:
        return None
    remaining = 100.0 - used_percent
    if remaining < 0.0:
        return 0.0
    if remaining > 100.0:
        return 100.0
    return remaining


def _confidence(used_percent: float | None, *, estimated: bool) -> QuotaConfidence:
    if used_percent is None:
        return "unknown"
    if estimated:
        return "estimated"
    return "established"


def _epoch_datetime(epoch: float | int | None) -> datetime | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(float(epoch), timezone.utc)


def _as_utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)
