"""Capacity routing for CLIProxyAPI credentials.

codex-lb picks the credential. Scoring goes through
``_select_with_stickiness`` in the Codex load balancer, which calls
``select_account``. Pins live in ``cliproxy_sticky_sessions`` because
``sticky_sessions.account_id`` references ``accounts.id`` and a CLIProxyAPI
credential id is not an account row.

A pinned ``<prefix>/<model>`` is registered only on the credential that owns
that prefix (``applyModelPrefixes`` in CLIProxyAPI
``sdk/cliproxy/service_models.go``). CLIProxyAPI's session-affinity selector
then sees that one credential, so the pin bypasses cross-account affinity.
``routing.force-model-prefix`` stays untouched. When this router cannot
choose, the wire model is left plain and CLIProxyAPI selects.

Eligibility uses each OAuth file's discovered models from
``GET /v0/management/auth-files/models``. ``model_states`` only names models
whose quota is already exhausted. When that catalog cannot be read, a
credential serves its provider family. API-key entries serve their
configured model list, or that same family when the list is empty.

Unknown capacity: an account with no measured quota window is scored as
fully used (100/100) so every measured account with remaining headroom
ranks ahead of it. It still serves when it is the sticky pin or when no
measured account is eligible. Missing weight counts as 1. A non-positive
weight is excluded. Under ``capacity_weighted`` the weight is the capacity
credit total, so remaining headroom scales with it. Other Codex strategies
keep their usage order. Missing priority counts as 0, and a cold selection
uses only the highest priority tier that still has an active account.
Higher integers win, matching ``authPriority`` in
``sdk/cliproxy/auth/selector.go``. A sticky pin stays on a lower tier
while that credential can still serve.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Literal, cast

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.balancer.logic import AccountState, RoutingStrategy
from app.core.clients.claude_sidecar import ClaudeSidecarClient
from app.core.config.settings_cache import get_settings_cache
from app.core.types import JsonValue
from app.core.utils.time import to_utc_naive, utcnow
from app.db.models import AccountStatus, CliproxyStickySession, DashboardSettings, StickySessionKind
from app.db.session import get_background_session
from app.modules.claude_sidecar.capacity_hold import StoredSnapshotReader
from app.modules.claude_sidecar.quota import SidecarAuthQuota, SidecarQuotaSnapshot, credential_provider
from app.modules.cliproxy_accounts.api_keys import (
    ApiKeyRouteRow,
    list_routing_api_keys,
    set_api_key_prefix_if_empty,
)
from app.modules.cliproxy_accounts.status_lock import cliproxy_api_key_list_lock, cliproxy_prefix_write_lock
from app.modules.cliproxy_accounts.validation import prefix_or_none
from app.modules.proxy._load_balancer.sticky_selection import (
    _select_with_stickiness,
    _sticky_refresh_write_skippable,
    _StickyMutation,
)
from app.modules.proxy.affinity import _sticky_key_from_session_header, _sticky_key_from_turn_state_header
from app.modules.proxy.cliproxy_quota_state import account_state_for_auth
from app.modules.proxy.sticky_repository import (
    _REFRESH_SKIP_MAX_SECONDS,
    _REFRESH_SKIP_TTL_FRACTION,
    StickySessionsRepository,
)

logger = logging.getLogger(__name__)

CliproxyRouteKind = Literal["sticky", "rebind", "selected"]
_UNKNOWN_USED_PERCENT = 100.0
_SNAPSHOTS = StoredSnapshotReader()
_API_KEY_CACHE: tuple[float, tuple[ApiKeyRouteRow, ...]] | None = None
_API_KEY_CACHE_SECONDS = 15.0
_MODEL_CACHE: tuple[float, dict[str, tuple[str, ...] | None]] | None = None
_MODEL_CACHE_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class CliproxyCandidate:
    account_id: str
    provider: str
    auth_index: str | None
    name: str
    prefix: str | None
    priority: int
    weight: int
    models: tuple[str, ...]
    excluded_models: tuple[str, ...]
    family_fallback: bool
    state: AccountState
    blocked_models: frozenset[str] = frozenset()
    api_key_kind: str | None = None
    api_key_index: int | None = None


@dataclass(frozen=True, slots=True)
class CliproxyDispatchChoice:
    account_id: str
    provider: str
    auth_index: str | None
    prefix: str
    wire_model: str
    requested_model: str
    route: CliproxyRouteKind
    sticky_key: str | None
    sticky_kind: StickySessionKind | None


_CURRENT_CHOICE: ContextVar[CliproxyDispatchChoice | None] = ContextVar(
    "cliproxy_dispatch_choice",
    default=None,
)


def cliproxy_log_attribution() -> tuple[str | None, str | None, str | None]:
    """Provider, auth index, and route kind for the credential this task chose."""

    choice = _CURRENT_CHOICE.get()
    if choice is None:
        return None, None, None
    return choice.provider, choice.auth_index, choice.route


def prompt_cache_key_from_body(body: Mapping[str, JsonValue]) -> str | None:
    value = body.get("prompt_cache_key")
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def rewrite_model_for_credential(model: str, prefix: str | None) -> str:
    """Return ``prefix/leaf``, leaving ``model`` unchanged when prefix is unusable."""

    credential_prefix = prefix_or_none(prefix)
    if credential_prefix is None:
        return model
    leaf = model.rsplit("/", 1)[-1]
    if not leaf:
        return model
    return f"{credential_prefix}/{leaf}"


def model_is_excluded(patterns: Sequence[str], model: str) -> bool:
    """Whether ``model`` matches a CLIProxyAPI excluded-model pattern.

    Matching follows ``matchWildcard`` in ``sdk/cliproxy/service_models.go``:
    ``*`` is a substring wildcard, and a pattern without ``*`` is exact.
    Comparison is case-insensitive so ``Claude-*`` still skips ``claude-sonnet``.
    """

    leaf = model.rsplit("/", 1)[-1].strip().casefold()
    if not leaf:
        return False
    for pattern in patterns:
        text = pattern.strip().casefold()
        if not text:
            continue
        target = leaf
        if "/" in text:
            target = model.strip().casefold()
        if _wildcard_match(text, target) or _wildcard_match(text.rsplit("/", 1)[-1], leaf):
            return True
    return False


def candidate_serves_model(candidate: CliproxyCandidate, model: str) -> bool:
    leaf = model.rsplit("/", 1)[-1].strip()
    if not leaf or model_is_excluded(candidate.excluded_models, leaf):
        return False
    folded = leaf.casefold()
    if folded in candidate.blocked_models:
        return False
    if candidate.models:
        names = {item.rsplit("/", 1)[-1].strip().casefold() for item in candidate.models}
        return folded in names
    if not candidate.family_fallback:
        return False
    return _model_family(leaf) == credential_provider(candidate.provider)


def generated_prefix(provider: str, identity: str, taken: set[str]) -> str:
    """Return a stable unused single-segment prefix for one credential."""

    digest = hashlib.sha256(f"{provider}:{identity}".encode()).hexdigest()[:10]
    base = f"lb{digest}"
    if base.casefold() not in taken:
        return base
    for suffix in range(2, 100):
        candidate = f"{base}-{suffix}"
        if candidate.casefold() not in taken:
            return candidate
    raise RuntimeError(f"no free CLIProxyAPI prefix for {provider}:{identity}")


async def choose_cliproxy_route(
    candidates: Sequence[CliproxyCandidate],
    *,
    model: str,
    sticky_key: str | None,
    sticky_kind: StickySessionKind | None,
    sticky_repo: StickySessionsRepository | None,
    sticky_enabled: bool,
    existing_account_id: str | None = None,
    refresh_skip_deadline: datetime | None = None,
    routing_strategy: RoutingStrategy = "usage_weighted",
    prefer_earlier_reset: bool = False,
    prefer_earlier_reset_window: Literal["primary", "secondary"] = "secondary",
    sticky_max_age_seconds: int | None = None,
    budget_threshold_pct: float = 95.0,
    secondary_budget_threshold_pct: float = 100.0,
) -> tuple[CliproxyDispatchChoice | None, _StickyMutation | None]:
    """Pick one prefixed credential and the sticky write that should follow."""

    prefixed = [item for item in candidates if prefix_or_none(item.prefix) and item.weight > 0]
    serving = [item for item in prefixed if candidate_serves_model(item, model)]
    if not serving:
        return None, None
    use_sticky = sticky_enabled and bool(sticky_key) and sticky_kind is not None and sticky_repo is not None
    pinned_id = existing_account_id if use_sticky else None
    pool = serving if pinned_id and any(item.account_id == pinned_id for item in serving) else _cold_pool(serving)
    states = [_ranked_state(item, penalize_unknown=item.account_id != pinned_id) for item in pool]
    sidecar_ids = frozenset(item.account_id for item in pool)
    outcome = await _select_with_stickiness(
        states=states,
        account_map={},
        sticky_key=sticky_key if use_sticky else None,
        sticky_kind=sticky_kind if use_sticky else None,
        reallocate_sticky=False,
        sticky_max_age_seconds=sticky_max_age_seconds,
        budget_threshold_pct=budget_threshold_pct,
        secondary_budget_threshold_pct=secondary_budget_threshold_pct,
        prefer_earlier_reset_accounts=prefer_earlier_reset,
        prefer_earlier_reset_window=prefer_earlier_reset_window,
        routing_strategy=routing_strategy,
        sticky_repo=sticky_repo if use_sticky else None,
        sticky_existing_account_id=pinned_id,
        sticky_refresh_skip_deadline=refresh_skip_deadline,
        sidecar_account_ids=sidecar_ids,
    )
    chosen = outcome.selection.account
    if chosen is None:
        return None, outcome.mutation
    match = next((item for item in pool if item.account_id == chosen.account_id), None)
    if match is None or prefix_or_none(match.prefix) is None:
        return None, outcome.mutation
    prefix = prefix_or_none(match.prefix)
    assert prefix is not None
    route = _route_kind(pinned_id, chosen.account_id, use_sticky)
    choice = CliproxyDispatchChoice(
        account_id=chosen.account_id,
        provider=match.provider,
        auth_index=match.auth_index,
        prefix=prefix,
        wire_model=rewrite_model_for_credential(model, prefix),
        requested_model=model,
        route=route,
        sticky_key=sticky_key if use_sticky else None,
        sticky_kind=sticky_kind if use_sticky else None,
    )
    return choice, outcome.mutation if use_sticky else None


async def apply_cliproxy_account_route(
    body: dict[str, JsonValue],
    *,
    headers: Mapping[str, str] | None = None,
    client: ClaudeSidecarClient | None = None,
) -> CliproxyDispatchChoice | None:
    """Rewrite ``body['model']`` when capacity routing can name a credential.

    A disabled switch, an unconfigured sidecar, or any selection failure
    leaves the model unchanged.
    """

    _CURRENT_CHOICE.set(None)
    model = body.get("model")
    if not isinstance(model, str) or not model.strip():
        return None
    try:
        settings = await get_settings_cache().get()
        if not _routing_active(settings):
            return None
        choice = await _select_dispatch(
            settings,
            model,
            headers=headers or {},
            client=client,
            prompt_cache_key=prompt_cache_key_from_body(body),
        )
    except Exception:
        logger.warning("cliproxy capacity route failed; leaving model unchanged", exc_info=True)
        return None
    if choice is None:
        return None
    body["model"] = choice.wire_model
    _CURRENT_CHOICE.set(choice)
    logger.info(
        "cliproxy capacity route=%s provider=%s auth_index=%s model=%s",
        choice.route,
        choice.provider,
        choice.auth_index,
        choice.wire_model,
    )
    return choice


async def rebind_cliproxy_account_route(
    body: dict[str, JsonValue],
    *,
    client: ClaudeSidecarClient | None = None,
) -> CliproxyDispatchChoice | None:
    """Move the pin off the credential that just failed and rewrite the model once."""

    current = _CURRENT_CHOICE.get()
    if current is None:
        return None
    try:
        settings = await get_settings_cache().get()
        if not _routing_active(settings):
            return None
        choice = await _select_dispatch(
            settings,
            current.requested_model,
            headers={},
            client=client,
            exclude_account_ids=frozenset({current.account_id}),
            sticky_key=current.sticky_key,
            sticky_kind=current.sticky_kind,
        )
    except Exception:
        logger.warning("cliproxy capacity rebind failed", exc_info=True)
        return None
    if choice is None or choice.account_id == current.account_id:
        return None
    rebound = replace(choice, route="rebind")
    body["model"] = rebound.wire_model
    _CURRENT_CHOICE.set(rebound)
    logger.info(
        "cliproxy capacity route=rebind provider=%s auth_index=%s model=%s",
        rebound.provider,
        rebound.auth_index,
        rebound.wire_model,
    )
    return rebound


def candidates_from_snapshot(
    snapshot: SidecarQuotaSnapshot | None,
    *,
    now: datetime,
) -> list[CliproxyCandidate]:
    if snapshot is None:
        return []
    built: list[CliproxyCandidate] = []
    for auth in snapshot.accounts:
        state = account_state_for_auth(auth, holds=snapshot.rate_limit_holds, now=now)
        if state is None:
            continue
        blocked = frozenset(
            item.model.strip().casefold() for item in auth.model_states if item.quota_exceeded and item.model.strip()
        )
        built.append(_oauth_candidate(auth, state, models=(), blocked=blocked))
    return built


def candidates_from_api_keys(rows: Sequence[ApiKeyRouteRow]) -> list[CliproxyCandidate]:
    built: list[CliproxyCandidate] = []
    for row in rows:
        provider = "openai-compatibility" if row.kind == "openai-compatibility" else row.kind
        identity = row.auth_index or f"{row.kind}:{row.index}"
        status = AccountStatus.PAUSED if row.disabled else AccountStatus.ACTIVE
        state = AccountState(
            account_id=f"cliproxy:{provider}:key:{identity}",
            status=status,
            plan_type=provider,
        )
        models = tuple(item for item in row.models if item.strip())
        built.append(
            CliproxyCandidate(
                account_id=state.account_id,
                provider=provider,
                auth_index=row.auth_index,
                name=row.name,
                prefix=prefix_or_none(row.prefix),
                priority=row.priority if row.priority is not None else 0,
                weight=1 if row.weight is None else row.weight,
                models=models,
                excluded_models=(),
                family_fallback=not models and provider in {"claude", "xai", "codex", "gemini"},
                state=state,
                api_key_kind=row.kind,
                api_key_index=row.index,
            )
        )
    return built


async def _select_dispatch(
    settings: DashboardSettings,
    model: str,
    *,
    headers: Mapping[str, str],
    client: ClaudeSidecarClient | None,
    prompt_cache_key: str | None = None,
    exclude_account_ids: frozenset[str] = frozenset(),
    sticky_key: str | None = None,
    sticky_kind: StickySessionKind | None = None,
) -> CliproxyDispatchChoice | None:
    now = datetime.now(timezone.utc)
    snapshot = _SNAPSHOTS.read(settings.claude_sidecar_quota_state_json)
    candidates = candidates_from_snapshot(snapshot, now=now)
    if client is not None:
        try:
            candidates.extend(candidates_from_api_keys(await _cached_api_keys(client)))
        except Exception:
            logger.info("cliproxy api-key list unavailable; routing oauth credentials only", exc_info=True)
        candidates = await _attach_discovered_models(candidates, client)
    if exclude_account_ids:
        candidates = [item for item in candidates if item.account_id not in exclude_account_ids]
    candidates = await _fill_empty_prefixes(candidates, model, client)
    sticky_enabled = bool(settings.sticky_threads_enabled)
    if sticky_key is None and sticky_kind is None:
        sticky_key, sticky_kind = _sticky_identity(
            prompt_cache_key,
            headers,
            sticky_enabled=sticky_enabled,
        )
    strategy = _routing_strategy(settings)
    prefer_reset = bool(settings.prefer_earlier_reset_accounts)
    reset_window = _reset_window(settings)
    if sticky_enabled and sticky_key and sticky_kind is not None:
        max_age = _sticky_max_age(settings, sticky_kind)
        async with get_background_session() as session:
            repo = _CliproxyStickyRepository(session)
            existing_id, refresh_deadline = await repo.lookup(sticky_key, kind=sticky_kind, max_age_seconds=max_age)
            choice, mutation = await choose_cliproxy_route(
                candidates,
                model=model,
                sticky_key=sticky_key,
                sticky_kind=sticky_kind,
                sticky_repo=cast(StickySessionsRepository, repo),
                sticky_enabled=True,
                existing_account_id=existing_id,
                refresh_skip_deadline=refresh_deadline,
                routing_strategy=strategy,
                prefer_earlier_reset=prefer_reset,
                prefer_earlier_reset_window=reset_window,
                sticky_max_age_seconds=max_age,
                budget_threshold_pct=_primary_budget(settings),
                secondary_budget_threshold_pct=_secondary_budget(settings),
            )
            await _apply_sticky_mutation(repo, sticky_key, sticky_kind, mutation)
            await session.commit()
        return choice
    choice, _mutation = await choose_cliproxy_route(
        candidates,
        model=model,
        sticky_key=None,
        sticky_kind=None,
        sticky_repo=None,
        sticky_enabled=False,
        routing_strategy=strategy,
        prefer_earlier_reset=prefer_reset,
        prefer_earlier_reset_window=reset_window,
    )
    return choice


def _sticky_identity_from_request(
    *,
    model_body_key: str | None,
    headers: Mapping[str, str],
    sticky_enabled: bool,
) -> tuple[str | None, StickySessionKind | None]:
    if not sticky_enabled:
        return None, None
    cache_key = model_body_key.strip() if isinstance(model_body_key, str) and model_body_key.strip() else ""
    if cache_key:
        return f"cliproxy:prompt_cache:{cache_key}", StickySessionKind.PROMPT_CACHE
    turn_state = _sticky_key_from_turn_state_header(headers)
    if turn_state and not turn_state.startswith(("turn_", "http_turn_")):
        return f"cliproxy:turn:{turn_state}", StickySessionKind.STICKY_THREAD
    session_key = _sticky_key_from_session_header(headers)
    if session_key:
        return f"cliproxy:session:{session_key}", StickySessionKind.STICKY_THREAD
    return None, None


def _sticky_identity(
    prompt_cache_key: str | None,
    headers: Mapping[str, str],
    *,
    sticky_enabled: bool,
) -> tuple[str | None, StickySessionKind | None]:
    return _sticky_identity_from_request(
        model_body_key=prompt_cache_key,
        headers=headers,
        sticky_enabled=sticky_enabled,
    )


def _oauth_candidate(
    auth: SidecarAuthQuota,
    state: AccountState,
    *,
    models: tuple[str, ...],
    blocked: frozenset[str],
) -> CliproxyCandidate:
    provider = credential_provider(auth.provider)
    return CliproxyCandidate(
        account_id=state.account_id,
        provider=provider,
        auth_index=auth.auth_index,
        name=auth.name,
        prefix=prefix_or_none(auth.prefix),
        priority=auth.priority if auth.priority is not None else 0,
        weight=1 if auth.weight is None else auth.weight,
        models=models,
        excluded_models=auth.excluded_models,
        family_fallback=not models,
        state=state,
        blocked_models=blocked,
    )


def _ranked_state(candidate: CliproxyCandidate, *, penalize_unknown: bool = True) -> AccountState:
    state = replace(candidate.state, capacity_credits=float(candidate.weight))
    measured = state.used_percent is not None or state.secondary_used_percent is not None
    if measured or not penalize_unknown:
        return state
    return replace(
        state,
        used_percent=_UNKNOWN_USED_PERCENT,
        secondary_used_percent=_UNKNOWN_USED_PERCENT,
    )


def _cold_pool(candidates: Sequence[CliproxyCandidate]) -> list[CliproxyCandidate]:
    by_priority: dict[int, list[CliproxyCandidate]] = {}
    for candidate in candidates:
        by_priority.setdefault(candidate.priority, []).append(candidate)
    for priority in sorted(by_priority, reverse=True):
        tier = by_priority[priority]
        if any(item.state.status == AccountStatus.ACTIVE for item in tier):
            return tier
    return list(candidates)


def _route_kind(previous: str | None, chosen: str, sticky: bool) -> CliproxyRouteKind:
    if not sticky or previous is None:
        return "selected"
    if previous == chosen:
        return "sticky"
    return "rebind"


def _routing_active(settings: DashboardSettings) -> bool:
    if not settings.cliproxy_capacity_routing_enabled:
        return False
    return bool((settings.claude_sidecar_base_url or "").strip())


def _routing_strategy(settings: DashboardSettings) -> RoutingStrategy:
    value = settings.routing_strategy
    if value in {
        "usage_weighted",
        "round_robin",
        "capacity_weighted",
        "relative_availability",
        "fill_first",
        "sequential_drain",
        "reset_drain",
        "single_account",
    }:
        return value
    return "capacity_weighted"


def _reset_window(settings: DashboardSettings) -> Literal["primary", "secondary"]:
    return "primary" if settings.prefer_earlier_reset_window == "primary" else "secondary"


def _primary_budget(settings: DashboardSettings) -> float:
    return float(settings.sticky_reallocation_primary_budget_threshold_pct)


def _secondary_budget(settings: DashboardSettings) -> float:
    return float(settings.sticky_reallocation_secondary_budget_threshold_pct)


def _sticky_max_age(settings: DashboardSettings, kind: StickySessionKind | None) -> int | None:
    if kind not in {StickySessionKind.PROMPT_CACHE, StickySessionKind.STICKY_THREAD}:
        return None
    raw = settings.http_responses_session_bridge_prompt_cache_idle_ttl_seconds
    if raw > 0:
        return raw
    return 3600


def _model_family(model: str) -> str | None:
    leaf = model.rsplit("/", 1)[-1].strip().casefold()
    if leaf.startswith("claude"):
        return "claude"
    if leaf.startswith("grok"):
        return "xai"
    if leaf.startswith("gemini"):
        return "gemini"
    if leaf.startswith("gpt") or "codex" in leaf:
        return "codex"
    return None


def _wildcard_match(pattern: str, value: str) -> bool:
    if "*" not in pattern:
        return pattern == value
    parts = pattern.split("*")
    cursor = 0
    for index, part in enumerate(parts):
        if not part:
            continue
        found = value.find(part, cursor)
        if found < 0:
            return False
        if index == 0 and not pattern.startswith("*") and found != 0:
            return False
        cursor = found + len(part)
    if not pattern.endswith("*") and parts[-1] and not value.endswith(parts[-1]):
        return False
    return True


async def _cached_api_keys(client: ClaudeSidecarClient) -> tuple[ApiKeyRouteRow, ...]:
    global _API_KEY_CACHE
    now = datetime.now(timezone.utc).timestamp()
    cached = _API_KEY_CACHE
    if cached is not None and now - cached[0] < _API_KEY_CACHE_SECONDS:
        return cached[1]
    rows = tuple(await list_routing_api_keys(client))
    _API_KEY_CACHE = (now, rows)
    return rows


def _drop_api_key_cache() -> None:
    global _API_KEY_CACHE
    _API_KEY_CACHE = None


async def _attach_discovered_models(
    candidates: list[CliproxyCandidate],
    client: ClaudeSidecarClient,
) -> list[CliproxyCandidate]:
    """Replace OAuth family guesses with the auth-file model catalog.

    A missing catalog entry leaves the candidate on family fallback. An empty
    catalog means the credential serves no model.
    """

    names = tuple(dict.fromkeys(item.name for item in candidates if item.api_key_kind is None and item.name))
    if not names:
        return candidates
    catalog = await _cached_auth_models(client, names)
    attached: list[CliproxyCandidate] = []
    for item in candidates:
        if item.api_key_kind is not None or not item.name:
            attached.append(item)
            continue
        found = catalog.get(item.name)
        if found is None:
            attached.append(item)
            continue
        attached.append(replace(item, models=found, family_fallback=False))
    return attached


async def _cached_auth_models(
    client: ClaudeSidecarClient,
    names: tuple[str, ...],
) -> dict[str, tuple[str, ...] | None]:
    """Discovered models by auth-file name. ``None`` means the read failed."""

    global _MODEL_CACHE
    now = datetime.now(timezone.utc).timestamp()
    cached = _MODEL_CACHE
    stored = dict(cached[1]) if cached is not None and now - cached[0] < _MODEL_CACHE_SECONDS else {}
    missing = tuple(name for name in names if name not in stored)
    if missing:
        fetched = await asyncio.gather(*(_read_auth_models(client, name) for name in missing))
        stored.update(dict(fetched))
        _MODEL_CACHE = (now, stored)
    return {name: stored.get(name) for name in names}


async def _read_auth_models(
    client: ClaudeSidecarClient,
    name: str,
) -> tuple[str, tuple[str, ...] | None]:
    try:
        models = tuple(item.strip() for item in await client.list_auth_file_models(name) if item.strip())
    except Exception:
        logger.info("cliproxy model catalog unavailable for %s", name)
        return name, None
    return name, models


async def _stored_prefixes(
    client: ClaudeSidecarClient,
) -> tuple[dict[str, str], dict[tuple[str, int], str], set[str]]:
    """Prefixes currently stored, read while the prefix lock is held."""

    oauth: dict[str, str] = {}
    for entry in await client.list_auth_files():
        name = entry.get("name")
        raw_prefix = entry.get("prefix")
        prefix = prefix_or_none(raw_prefix if isinstance(raw_prefix, str) else None)
        if isinstance(name, str) and name.strip() and prefix:
            oauth[name.strip()] = prefix
    api: dict[tuple[str, int], str] = {}
    for row in await list_routing_api_keys(client):
        prefix = prefix_or_none(row.prefix)
        if prefix:
            api[(row.kind, row.index)] = prefix
    taken = {prefix.casefold() for prefix in oauth.values()}
    taken.update(prefix.casefold() for prefix in api.values())
    return oauth, api, taken


def _known_prefix(
    candidate: CliproxyCandidate,
    oauth_prefixes: Mapping[str, str],
    api_prefixes: Mapping[tuple[str, int], str],
) -> str | None:
    if candidate.api_key_kind is not None and candidate.api_key_index is not None:
        return api_prefixes.get((candidate.api_key_kind, candidate.api_key_index))
    if not candidate.name:
        return None
    return oauth_prefixes.get(candidate.name)


async def _fill_empty_prefixes(
    candidates: list[CliproxyCandidate],
    model: str,
    client: ClaudeSidecarClient | None,
) -> list[CliproxyCandidate]:
    if client is None:
        return candidates
    needing = [
        item
        for item in candidates
        if prefix_or_none(item.prefix) is None and item.weight > 0 and candidate_serves_model(item, model)
    ]
    if not needing:
        return candidates
    assigned: dict[str, str] = {}
    try:
        async with get_background_session() as session:
            async with cliproxy_prefix_write_lock(session):
                oauth_prefixes, api_prefixes, taken = await _stored_prefixes(client)
                for item in needing:
                    existing = _known_prefix(item, oauth_prefixes, api_prefixes)
                    if existing:
                        assigned[item.account_id] = existing
                        taken.add(existing.casefold())
                        continue
                    prefix = generated_prefix(item.provider, item.account_id, taken)
                    stored = await _store_prefix_if_empty(client, session, item, prefix)
                    if stored:
                        assigned[item.account_id] = stored
                        taken.add(stored.casefold())
    except Exception:
        logger.warning("cliproxy prefix assignment failed; unprefixed credentials stay unpinned", exc_info=True)
        return candidates
    if assigned:
        _drop_api_key_cache()
    if not assigned:
        return candidates
    return [replace(item, prefix=assigned.get(item.account_id, item.prefix)) for item in candidates]


async def _store_prefix_if_empty(
    client: ClaudeSidecarClient,
    session: AsyncSession,
    candidate: CliproxyCandidate,
    prefix: str,
) -> str | None:
    if candidate.api_key_kind is not None and candidate.api_key_index is not None:
        async with cliproxy_api_key_list_lock(session, candidate.api_key_kind):
            return await set_api_key_prefix_if_empty(
                client,
                kind_slug=candidate.api_key_kind,
                index=candidate.api_key_index,
                prefix=prefix,
            )
    if not candidate.name:
        return None
    await client.patch_auth_file_fields(candidate.name, {"prefix": prefix})
    return prefix


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
        account_id, _deadline = await self.lookup(key, kind=kind, max_age_seconds=max_age_seconds)
        return account_id

    async def lookup(
        self,
        key: str,
        *,
        kind: StickySessionKind,
        max_age_seconds: int | None = None,
    ) -> tuple[str | None, datetime | None]:
        if kind == StickySessionKind.CODEX_SESSION:
            return None, None
        row = await self._session.get(CliproxyStickySession, (key, kind.value))
        if row is None:
            return None, None
        updated = to_utc_naive(row.updated_at)
        now = utcnow()
        if max_age_seconds is not None and now - updated > timedelta(seconds=max_age_seconds):
            return None, None
        deadline = None
        if max_age_seconds is not None:
            deadline = _refresh_skip_deadline(updated, now=now, max_age_seconds=max_age_seconds)
        return row.account_id, deadline

    async def upsert(self, key: str, account_id: str, kind: StickySessionKind) -> None:
        if kind == StickySessionKind.CODEX_SESSION:
            return
        now = datetime.now(timezone.utc)
        dialect = self._session.get_bind().dialect.name
        insert_fn = pg_insert if dialect == "postgresql" else sqlite_insert
        if dialect not in {"postgresql", "sqlite"}:
            raise RuntimeError(f"CLIProxy sticky upsert unsupported for dialect={dialect!r}")
        statement = insert_fn(CliproxyStickySession).values(
            key=key,
            kind=kind.value,
            account_id=account_id,
            updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[CliproxyStickySession.key, CliproxyStickySession.kind],
            set_={"account_id": account_id, "updated_at": now},
        )
        await self._session.execute(statement)

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
    if mutation.account_id is None:
        await repo.delete(key, kind)
        return
    if _sticky_refresh_write_skippable(mutation, initialize_seed_key=None):
        return
    await repo.upsert(key, mutation.account_id, kind)


def _refresh_skip_deadline(updated_at: datetime, *, now: datetime, max_age_seconds: int) -> datetime | None:
    age_seconds = (now - updated_at).total_seconds()
    if age_seconds < 0:
        return None
    skip_window_seconds = min(_REFRESH_SKIP_MAX_SECONDS, max_age_seconds * _REFRESH_SKIP_TTL_FRACTION)
    if age_seconds > skip_window_seconds:
        return None
    return updated_at + timedelta(seconds=skip_window_seconds)
