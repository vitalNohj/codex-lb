"""Pick one CLIProxyAPI credential for a sidecar request.

The pool stays off until :func:`cliproxy_account_pool_enabled` is true. While
it is false this module does not read quota, prefixes, or sticky rows, and it
does not rewrite the wire model. ``force-model-prefix`` is never written:
a missed selection leaves the unprefixed model CLIProxyAPI already accepts.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.balancer.logic import AccountState
from app.core.config.settings_cache import get_settings_cache
from app.core.types import JsonValue
from app.db.models import AccountStatus, CliproxyStickySession, StickySessionKind
from app.db.session import get_background_session
from app.modules.claude_sidecar.capacity_hold import StoredSnapshotReader
from app.modules.claude_sidecar.quota import (
    GrokCreditsQuota,
    GrokCreditWindow,
    SidecarAuthQuota,
    SidecarOAuthUsageBucket,
    SidecarRateLimitHold,
    credential_provider,
)
from app.modules.claude_sidecar.rate_limit_hold import XAI_FREE_USAGE_HOLD, XAI_LIMIT_FREE_USAGE
from app.modules.cliproxy_accounts.repository import CliproxyCredentialPrefixRepository
from app.modules.cliproxy_accounts.summaries import cliproxy_account_pool_enabled
from app.modules.proxy._load_balancer.sticky_selection import _select_with_stickiness, _StickyMutation
from app.modules.proxy.sticky_repository import StickySessionsRepository

logger = logging.getLogger(__name__)

_QUOTA_SOURCES = frozenset({"codex", "claude", "xai"})
_XAI_WINDOW_KINDS = frozenset({"weekly", "monthly", "credits"})


@dataclass(frozen=True, slots=True)
class CliproxyDispatchChoice:
    account_id: str
    provider: str
    auth_index: str | None
    prefix: str
    wire_model: str
    requested_model: str
    sticky_key: str | None
    sticky_kind: StickySessionKind | None


_CURRENT_CHOICE: ContextVar[CliproxyDispatchChoice | None] = ContextVar(
    "cliproxy_dispatch_choice",
    default=None,
)


def cliproxy_log_attribution() -> tuple[str | None, str | None]:
    """Provider and auth index of the credential selected for this task."""

    choice = _CURRENT_CHOICE.get()
    if choice is None:
        return None, None
    return choice.provider, choice.auth_index


def prompt_cache_key_from_body(body: Mapping[str, JsonValue]) -> str | None:
    """Read an OpenAI ``prompt_cache_key`` when the client sent one."""

    value = body.get("prompt_cache_key")
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def rewrite_model_for_credential(model: str, prefix: str | None, *, strip: bool) -> str:
    """Return the wire model for one credential prefix.

    ``strip=False`` is the dispatch path: an empty prefix leaves ``model``
    unchanged, and a real prefix replaces any existing leading segment with
    exactly one ``prefix/leaf``. ``strip=True`` removes a matching leading
    ``prefix/`` and otherwise leaves the model alone.
    """

    credential_prefix = _single_segment(prefix)
    if credential_prefix is None:
        return model
    head, separator, tail = model.partition("/")
    if strip:
        if separator and head == credential_prefix and tail:
            return tail
        return model
    leaf = model.rsplit("/", 1)[-1]
    if not leaf:
        return model
    rewritten = f"{credential_prefix}/{leaf}"
    if model == rewritten:
        return model
    return rewritten


def account_state_for_auth(
    auth: SidecarAuthQuota,
    *,
    holds: Sequence[SidecarRateLimitHold],
    prefix: str | None,
    now: datetime,
) -> AccountState | None:
    """Map one credential onto the selector's account interface.

    Credentials without a single-segment prefix are not exact-targetable and
    are left out of the pool. Real Codex window math stays on Codex
    ``AccountState`` rows; a CLIProxyAPI credential tagged ``codex`` uses OAuth
    buckets when the snapshot has them and otherwise stays unknown.
    """

    credential_prefix = _single_segment(prefix)
    if credential_prefix is None:
        return None
    provider = credential_provider(auth.provider)
    identity = auth.auth_index.strip() if isinstance(auth.auth_index, str) and auth.auth_index.strip() else auth.name
    if not identity:
        return None
    moment = _as_utc(now)
    hold = _active_hold(auth, holds, moment)
    source = provider if provider in _QUOTA_SOURCES else "unknown"
    status, used_percent, reset_at, secondary_used, secondary_reset = _quota_fields(
        auth,
        source=source,
        hold=hold,
        now=moment,
    )
    return AccountState(
        account_id=f"cliproxy:{provider}:{identity}",
        status=status,
        used_percent=used_percent,
        reset_at=reset_at,
        secondary_used_percent=secondary_used,
        secondary_reset_at=int(secondary_reset) if secondary_reset is not None else None,
        plan_type=provider,
    )


async def apply_cliproxy_account_route(
    body: dict[str, JsonValue],
    *,
    prompt_cache_key: str | None,
) -> CliproxyDispatchChoice | None:
    """Rewrite ``body['model']`` to the selected credential prefix.

    Returns None when the pool is off, no prefixed credential can serve the
    model, or a read fails. A failure leaves the wire model unchanged so Claude
    traffic keeps today's unprefixed forward.
    """

    if not cliproxy_account_pool_enabled():
        _CURRENT_CHOICE.set(None)
        return None
    model = body.get("model")
    if not isinstance(model, str) or not model.strip():
        _CURRENT_CHOICE.set(None)
        return None
    _CURRENT_CHOICE.set(None)
    try:
        choice = await _select_dispatch(
            model,
            prompt_cache_key=prompt_cache_key,
            exclude_account_ids=frozenset(),
        )
    except Exception:
        logger.warning("cliproxy account route failed; leaving model unchanged", exc_info=True)
        return None
    if choice is None:
        return None
    body["model"] = choice.wire_model
    _CURRENT_CHOICE.set(choice)
    return choice


async def rebind_cliproxy_account_route(body: dict[str, JsonValue]) -> CliproxyDispatchChoice | None:
    """Move the sticky pin off the credential that just failed and rewrite once."""

    if not cliproxy_account_pool_enabled():
        return None
    current = _CURRENT_CHOICE.get()
    if current is None:
        return None
    try:
        choice = await _select_dispatch(
            current.requested_model,
            prompt_cache_key=_prompt_cache_key_from_sticky(current),
            exclude_account_ids=frozenset({current.account_id}),
            sticky_key=current.sticky_key,
            sticky_kind=current.sticky_kind,
        )
    except Exception:
        logger.warning("cliproxy account rebind failed", exc_info=True)
        return None
    if choice is None or choice.account_id == current.account_id:
        return None
    body["model"] = choice.wire_model
    _CURRENT_CHOICE.set(choice)
    return choice


def _prompt_cache_key_from_sticky(choice: CliproxyDispatchChoice) -> str | None:
    if choice.sticky_kind != StickySessionKind.PROMPT_CACHE or not choice.sticky_key:
        return None
    marker = "cliproxy:prompt_cache:"
    if not choice.sticky_key.startswith(marker):
        return None
    value = choice.sticky_key.removeprefix(marker)
    return value or None


async def _select_dispatch(
    model: str,
    *,
    prompt_cache_key: str | None,
    exclude_account_ids: frozenset[str],
    sticky_key: str | None = None,
    sticky_kind: StickySessionKind | None = None,
) -> CliproxyDispatchChoice | None:
    settings = await get_settings_cache().get()
    snapshot = StoredSnapshotReader().read(settings.claude_sidecar_quota_state_json)
    accounts = snapshot.accounts if snapshot is not None else ()
    holds = snapshot.rate_limit_holds if snapshot is not None else ()
    now = datetime.now(timezone.utc)
    if sticky_key is None and sticky_kind is None:
        sticky_key, sticky_kind = _sticky_identity(
            prompt_cache_key,
            max_age_seconds=settings.http_responses_session_bridge_prompt_cache_idle_ttl_seconds,
        )
    max_age = (
        settings.http_responses_session_bridge_prompt_cache_idle_ttl_seconds
        if sticky_kind in (StickySessionKind.PROMPT_CACHE, StickySessionKind.STICKY_THREAD)
        else None
    )
    async with get_background_session() as session:
        prefixes = await CliproxyCredentialPrefixRepository(session).list_all()
        by_name = {row.credential_name: row.prefix for row in prefixes}
        by_index = {row.auth_index: row.prefix for row in prefixes if row.auth_index}
        built: list[tuple[AccountState, SidecarAuthQuota, str]] = []
        for auth in accounts:
            prefix = _prefix_for_auth(auth, by_name, by_index)
            if not _serves_model(auth, model):
                continue
            state = account_state_for_auth(auth, holds=holds, prefix=prefix, now=now)
            if state is None or state.account_id in exclude_account_ids or prefix is None:
                continue
            built.append((state, auth, prefix))
        if not built:
            return None
        states = [state for state, _auth, _prefix in built]
        sidecar_ids = frozenset(state.account_id for state in states)
        repo = _CliproxyStickyRepository(session)
        outcome = await _select_with_stickiness(
            states=states,
            account_map={},
            sticky_key=sticky_key,
            sticky_kind=sticky_kind,
            reallocate_sticky=False,
            sticky_max_age_seconds=max_age,
            prefer_earlier_reset_accounts=False,
            prefer_earlier_reset_window="secondary",
            routing_strategy="usage_weighted",
            sticky_repo=cast(StickySessionsRepository, repo),
            sidecar_account_ids=sidecar_ids,
        )
        chosen = outcome.selection.account
        if chosen is None:
            return None
        await _apply_sticky_mutation(repo, sticky_key, sticky_kind, outcome.mutation)
        await session.commit()
    match = next((item for item in built if item[0].account_id == chosen.account_id), None)
    if match is None:
        return None
    _state, auth, prefix = match
    provider = credential_provider(auth.provider)
    wire_model = rewrite_model_for_credential(model, prefix, strip=False)
    return CliproxyDispatchChoice(
        account_id=chosen.account_id,
        provider=provider,
        auth_index=auth.auth_index,
        prefix=prefix,
        wire_model=wire_model,
        requested_model=model,
        sticky_key=sticky_key,
        sticky_kind=sticky_kind,
    )


def _sticky_identity(
    prompt_cache_key: str | None,
    *,
    max_age_seconds: int,
) -> tuple[str | None, StickySessionKind | None]:
    del max_age_seconds
    text = prompt_cache_key.strip() if isinstance(prompt_cache_key, str) else ""
    if not text:
        return None, None
    return f"cliproxy:prompt_cache:{text}", StickySessionKind.PROMPT_CACHE


def _serves_model(auth: SidecarAuthQuota, model: str) -> bool:
    """Keep a credential only when the model leaf names its provider.

    An unrecognized leaf stays unprefixed. ``force-model-prefix`` is false, so
    CLIProxyAPI keeps routing that id itself.
    """

    family = _model_family(model)
    if family is None:
        return False
    return credential_provider(auth.provider) == family


def _model_family(model: str) -> str | None:
    leaf = model.rsplit("/", 1)[-1].strip().lower()
    if leaf.startswith("claude"):
        return "claude"
    if leaf.startswith("grok"):
        return "xai"
    if leaf.startswith("gpt") or "codex" in leaf:
        return "codex"
    return None


def _prefix_for_auth(
    auth: SidecarAuthQuota,
    by_name: dict[str, str],
    by_index: dict[str, str],
) -> str | None:
    registered = by_name.get(auth.name)
    if registered is None and auth.auth_index:
        registered = by_index.get(auth.auth_index)
    if registered is None:
        registered = auth.prefix
    return _single_segment(registered)


def _single_segment(prefix: str | None) -> str | None:
    if prefix is None:
        return None
    text = prefix.strip()
    if not text or "/" in text or any(character.isspace() for character in text):
        return None
    return text


def _quota_fields(
    auth: SidecarAuthQuota,
    *,
    source: str,
    hold: SidecarRateLimitHold | None,
    now: datetime,
) -> tuple[AccountStatus, float | None, float | None, float | None, float | None]:
    status = _status_for_auth(auth, hold)
    if source == "xai":
        used, reset_at = _xai_usage(auth.grok_credits, hold, status, now)
        return status, used, reset_at, None, None
    if source in {"claude", "codex"} and auth.oauth_usage is not None:
        primary_used, primary_reset = _used_from_bucket(auth.oauth_usage.five_hour)
        secondary_used, secondary_reset = _used_from_bucket(auth.oauth_usage.seven_day)
        if status == AccountStatus.RATE_LIMITED and hold is not None:
            return status, 100.0, _epoch(hold.until), secondary_used, secondary_reset
        return status, primary_used, primary_reset, secondary_used, secondary_reset
    if status == AccountStatus.RATE_LIMITED and hold is not None:
        return status, 100.0, _epoch(hold.until), None, None
    return status, None, None, None, None


def _status_for_auth(auth: SidecarAuthQuota, hold: SidecarRateLimitHold | None) -> AccountStatus:
    status_text = (auth.status or "").strip().lower()
    message = (auth.status_message or "").lower()
    if status_text in {"unauthorized", "reauth", "reauth_required"} or "reauth" in message:
        return AccountStatus.REAUTH_REQUIRED
    if auth.disabled or auth.unavailable:
        return AccountStatus.PAUSED
    if auth.quota_exceeded:
        return AccountStatus.QUOTA_EXCEEDED
    if _xai_free_exhausted(auth, hold) or hold is not None:
        return AccountStatus.RATE_LIMITED
    return AccountStatus.ACTIVE


def _xai_free_exhausted(auth: SidecarAuthQuota, hold: SidecarRateLimitHold | None) -> bool:
    credits = auth.grok_credits
    if credits is not None and credits.observed_limit == XAI_LIMIT_FREE_USAGE:
        return True
    return hold is not None and hold.kind == XAI_LIMIT_FREE_USAGE


def _xai_usage(
    credits: GrokCreditsQuota | None,
    hold: SidecarRateLimitHold | None,
    status: AccountStatus,
    now: datetime,
) -> tuple[float | None, float | None]:
    if status == AccountStatus.RATE_LIMITED:
        if hold is not None:
            return 100.0, _epoch(hold.until)
        return 100.0, (now + XAI_FREE_USAGE_HOLD).timestamp()
    window = _xai_window(credits)
    if window is None:
        return None, None
    return _clamp_percent(window.percent_used), _epoch(window.resets_at)


def _xai_window(credits: GrokCreditsQuota | None) -> GrokCreditWindow | None:
    if credits is None or not credits.windows:
        return None
    for window in credits.windows:
        if window.id == "credits" or window.kind in _XAI_WINDOW_KINDS:
            return window
    return credits.windows[0]


def _used_from_bucket(bucket: SidecarOAuthUsageBucket | None) -> tuple[float | None, float | None]:
    if bucket is None or bucket.remaining_percent is None:
        return None, None
    return _clamp_percent(100.0 - bucket.remaining_percent), _epoch(bucket.resets_at)


def _active_hold(
    auth: SidecarAuthQuota,
    holds: Sequence[SidecarRateLimitHold],
    now: datetime,
) -> SidecarRateLimitHold | None:
    provider = credential_provider(auth.provider)
    for hold in holds:
        if hold.released or hold.name != auth.name:
            continue
        if credential_provider(hold.provider) != provider:
            continue
        if _as_utc(hold.until) > now:
            return hold
    return None


def _clamp_percent(value: float) -> float:
    if value < 0:
        return 0.0
    if value > 100:
        return 100.0
    return value


def _epoch(moment: datetime | None) -> float | None:
    if moment is None:
        return None
    return _as_utc(moment).timestamp()


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


class _CliproxyStickyRepository:
    """Sticky lookup for credential ids that are not ``accounts`` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_account_id(
        self,
        key: str,
        *,
        kind: StickySessionKind,
        max_age_seconds: int | None = None,
    ) -> str | None:
        if kind == StickySessionKind.CODEX_SESSION:
            return None
        row = await self._session.get(CliproxyStickySession, (key, kind.value))
        if row is None:
            return None
        if max_age_seconds is not None:
            updated = _as_utc(row.updated_at)
            if datetime.now(timezone.utc) - updated > timedelta(seconds=max_age_seconds):
                return None
        return row.account_id

    async def upsert(self, key: str, account_id: str, kind: StickySessionKind) -> None:
        if kind == StickySessionKind.CODEX_SESSION:
            return
        now = datetime.now(timezone.utc)
        row = await self._session.get(CliproxyStickySession, (key, kind.value))
        if row is None:
            self._session.add(
                CliproxyStickySession(
                    key=key,
                    kind=kind.value,
                    account_id=account_id,
                    updated_at=now,
                )
            )
            return
        row.account_id = account_id
        row.updated_at = now

    async def delete(self, key: str, kind: StickySessionKind) -> None:
        row = await self._session.get(CliproxyStickySession, (key, kind.value))
        if row is not None:
            await self._session.delete(row)


async def _apply_sticky_mutation(
    repo: _CliproxyStickyRepository,
    key: str | None,
    kind: StickySessionKind | None,
    mutation: _StickyMutation | None,
) -> None:
    if key is None or kind is None or mutation is None:
        return
    if kind == StickySessionKind.CODEX_SESSION:
        return
    if mutation.account_id is None:
        await repo.delete(key, kind)
        return
    await repo.upsert(key, mutation.account_id, kind)
