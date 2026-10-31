"""Capacity routing for CLIProxyAPI credentials.

codex-lb picks the credential. Scoring goes through
``_select_with_stickiness`` in the Codex load balancer, which calls
``select_account``. Pins live in ``cliproxy_sticky_sessions`` because
``sticky_sessions.account_id`` references ``accounts.id`` and a CLIProxyAPI
credential id is not an account row.

A pinned ``<prefix>/<model-id>`` is registered only on the credential that owns
that prefix (``applyModelPrefixes`` in CLIProxyAPI
``sdk/cliproxy/service_models.go``). The model id keeps every segment the
client sent. A leading segment is removed only when it is already a known
credential prefix, so a second pass does not nest prefixes. CLIProxyAPI's
session-affinity selector then sees that one credential, so the pin bypasses
cross-account affinity. ``routing.force-model-prefix`` stays untouched. When
this router cannot choose, the wire model is left plain and CLIProxyAPI selects.

Eligibility uses each OAuth file's discovered models from
``GET /v0/management/auth-files/models``. ``model_states`` only names models
whose quota is already exhausted. When that catalog cannot be read, a
credential serves its provider family. API-key entries serve their
configured model list, or that same family when the list is empty.

Unknown capacity: an account with no measured quota window is scored at a
neutral 50/50. A measured account with more headroom ranks ahead of it, a
nearly spent one ranks behind it, and a new or API-key credential is not
starved just because no quota snapshot names it. Missing weight counts as 1. A non-positive
weight is excluded. Under ``capacity_weighted`` the weight is the capacity
credit total, so remaining headroom scales with it. ``round_robin`` uses the
same least-recently-selected order as Codex accounts; those timestamps stay
in this process, the way the Codex balancer keeps them on the account
runtime. Other strategies keep their usage order. A prefix learned from a
successful fill is remembered here so a stale quota snapshot does not take
the prefix lock again. Missing priority counts as 0, and a cold selection
uses only the highest priority tier that still has an active account.
Higher integers win, matching ``authPriority`` in
``sdk/cliproxy/auth/selector.go``. A sticky pin stays on a lower tier
while that credential can still serve.

Sticky identity follows CLIProxyAPI's ``ExtractSessionID``
(``sdk/cliproxy/auth/selector.go``) and LiteLLM's ``session_affinity``: the
client's ``prompt_cache_key``, then the Codex turn-state and session headers,
then ``X-Claude-Code-Session-Id``, ``X-Session-Id``, ``X-Session-Affinity`` and
any other ``x-<vendor>-session-id``, then a body ``session_id`` or
``metadata.session_id``. Without any of those the key is derived from the
conversation content with the Codex recipe (``_derive_prompt_cache_key``):
API key, model class, system text and first user message. OpenRouter's
default sticky key is the same kind of first-messages hash.

A transient 401, 403 or 429 on a pinned credential keeps the pin. The
failed credential cools down in this process, and the conversation is served
by a second pin in the ``cliproxy:fallback:`` namespace so it stays on one
spare account. Once the cooldown ends the conversation returns to its warm pin.
LiteLLM >= 1.97 keeps the session pin the same way while the deployment is in
cooldown, and OpenRouter does not update the sticky provider on an error.
A pin created by the failing request itself has no warm cache and moves.

Pin writes are compare-and-set: a write applies only while the row still
names the account this request read, or the row has expired. A request that
loses the race re-reads the winner and routes there, so concurrent first
turns of one conversation land on one credential.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Literal, cast

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.balancer.logic import AccountState, RoutingStrategy, select_account
from app.core.clients.claude_sidecar import ClaudeSidecarClient
from app.core.clock import REAL_CLOCK
from app.core.config.settings_cache import get_settings_cache
from app.core.metrics.prometheus import cliproxy_claude_sticky_cache_total, cliproxy_route_outcome_total
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.core.openai.requests import ResponsesRequest
from app.core.types import JsonValue
from app.core.utils.time import to_utc_naive, utcnow
from app.db.models import AccountStatus, CliproxyStickySession, DashboardSettings, StickySessionKind
from app.db.session import get_background_session, sqlite_writer_section
from app.modules.claude_sidecar.auth_file import stored_prefix_for_entry
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
from app.modules.proxy.affinity import (
    _sticky_key_from_session_header,
    _sticky_key_from_turn_state_header,
    derive_content_prompt_cache_key,
)
from app.modules.proxy.cliproxy_quota_state import account_state_for_auth
from app.modules.proxy.sticky_repository import (
    _REFRESH_SKIP_MAX_SECONDS,
    _REFRESH_SKIP_TTL_FRACTION,
    StickySessionsRepository,
    cliproxy_sticky_max_age_seconds,
)

logger = logging.getLogger(__name__)

CliproxyRouteKind = Literal["sticky", "rebind", "selected"]
CliproxyRouteOutcome = Literal[
    "selected",
    "sticky",
    "rebind",
    "unpinned_no_key",
    "fail_open",
    "no_candidate",
    "refused",
]
CliproxyKeySource = Literal[
    "prompt_cache_key",
    "turn_state",
    "session_header",
    "body_session_id",
    "derived",
    "none",
    "disabled",
    "unknown",
]
_UNKNOWN_USED_PERCENT = 50.0
# A credential that just answered 401/403/429 is skipped for this long. The
# conversation pin stays on it, so the next turn after the cooldown returns
# to the warm cache. Matches LiteLLM's router cooldown (keep the pin, fall
# through while the deployment cools down).
_COOLDOWN_SECONDS = 60.0
_COOLING: dict[str, float] = {}
# Fallback pins live in their own namespace. No client identity resolves to
# it (see ``_resolve_sticky_identity``), and the primary key is hashed, so a
# client session id cannot address another conversation's fallback row.
_FALLBACK_KEY_PREFIX = "cliproxy:fallback:"
# Pin states the shared selection moves away from rather than waiting out.
_UNUSABLE_PIN_STATUSES = frozenset(
    {
        AccountStatus.QUOTA_EXCEEDED,
        AccountStatus.REAUTH_REQUIRED,
        AccountStatus.PAUSED,
        AccountStatus.DEACTIVATED,
    }
)
# One compare-and-set write plus up to two retries after losing a race.
_CLAIM_ATTEMPTS = 3
_IDENTITY_MAX_CHARS = 256
_NO_CANDIDATE_WARN_SECONDS = 60.0
_NO_CANDIDATE_WARNED: OrderedDict[str, float] = OrderedDict()
_NO_CANDIDATE_WARN_LIMIT = 256
# The largest minimum cacheable prompt Anthropic documents (Opus 4.5/4.6).
# Below a model's minimum a prompt is silently uncached, which is not a fault,
# so only prompts at least this long count toward the cache-miss signal.
CLAUDE_CACHEABLE_PROMPT_TOKENS = 4096
_CACHE_MISS_WARN_SECONDS = 600.0
_CACHE_MISS_WARNED: OrderedDict[str, float] = OrderedDict()
# Session headers in the order CLIProxyAPI's ``ExtractSessionID`` reads them,
# after the Codex headers this router already honoured. Any other
# ``x-<vendor>-session-id`` follows, as in LiteLLM's ``session_affinity``.
_CLIENT_SESSION_HEADERS = ("x-claude-code-session-id", "x-session-id", "x-session-affinity")
_VENDOR_SESSION_HEADER = re.compile(r"^x-[a-z0-9]+(?:-[a-z0-9]+)*-session-id$")
_SNAPSHOTS = StoredSnapshotReader()
# The last snapshot that named accounts. A management outage replaces the stored
# snapshot with an empty unauthorized/unreachable/error payload; routing keeps
# using this one until a healthy poll names accounts again. A healthy empty poll
# clears it, so a later failure cannot resurrect a credential the operator removed.
_LAST_GOOD_SNAPSHOT: SidecarQuotaSnapshot | None = None
_API_KEY_CACHE: tuple[float, tuple[ApiKeyRouteRow, ...]] | None = None
# Rows from the last successful API-key listing. Kept without a TTL so a
# management outage does not drop API-key credentials after the short cache expires.
_LAST_GOOD_API_KEYS: tuple[ApiKeyRouteRow, ...] = ()
_API_KEY_CACHE_SECONDS = 15.0
_MODEL_CACHE: tuple[float, dict[str, tuple[str, ...] | None]] | None = None
_MODEL_CACHE_SECONDS = 15.0
# One warning for a stretch of failed management reads, not one per request.
_MANAGEMENT_OUTAGE: tuple[str, float] | None = None
_MANAGEMENT_OUTAGE_WARN_SECONDS = 60.0
_LAST_SELECTED: OrderedDict[str, float] = OrderedDict()
_LAST_SELECTED_LIMIT = 1024
_PREFIX_OVERLAY: OrderedDict[str, tuple[float, str]] = OrderedDict()
_PREFIX_OVERLAY_LIMIT = 256
_PREFIX_OVERLAY_SECONDS = 60.0


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
    route_identity: str | None = None


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
    key_source: CliproxyKeySource = "none"
    # True when this request is served by the conversation's fallback pin
    # while its own pin cools down.
    fallback: bool = False


@dataclass(frozen=True, slots=True)
class CliproxyStickyHints:
    """Conversation identity read from the client request before it is reshaped.

    The sidecar body drops ``metadata`` before routing, and a key the API
    layer derived must rank below the client's session headers, so the
    dispatcher reads these from the original request.
    """

    prompt_cache_key: str | None = None
    body_session_id: str | None = None
    derived_key: str | None = None


@dataclass(frozen=True, slots=True)
class _StickyIdentity:
    key: str | None
    kind: StickySessionKind | None
    source: CliproxyKeySource
    # The conversation id inside ``key``, without the ``cliproxy:<kind>:``
    # namespace. The native xAI Responses route forwards it as
    # ``prompt_cache_key`` so the pin and CLIProxyAPI's conversation id agree.
    value: str | None = None


@dataclass(frozen=True, slots=True)
class _RouteParams:
    strategy: RoutingStrategy
    prefer_reset: bool
    reset_window: Literal["primary", "secondary"]
    max_age: int | None
    primary_budget: float
    secondary_budget: float


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


def rewrite_model_for_credential(
    model: str,
    prefix: str | None,
    *,
    known_prefixes: Sequence[str] = (),
) -> str:
    """Return ``prefix`` plus the full model id.

    A leading segment is removed only when it is one of ``known_prefixes``.
    ``openrouter/auto`` stays ``openrouter/auto`` under the credential prefix.
    """

    credential_prefix = prefix_or_none(prefix)
    if credential_prefix is None:
        return model
    body = _model_without_known_prefix(model, known_prefixes).strip()
    if not body:
        return model
    return f"{credential_prefix}/{body}"


def _model_without_known_prefix(model: str, known_prefixes: Sequence[str]) -> str:
    text = model.strip()
    head, separator, tail = text.partition("/")
    if not separator or not tail:
        return text
    known = {item.casefold() for item in known_prefixes if prefix_or_none(item)}
    if head.casefold() in known:
        return tail
    return text


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


def candidate_serves_model(
    candidate: CliproxyCandidate,
    model: str,
    *,
    known_prefixes: Sequence[str] = (),
) -> bool:
    requested = _model_without_known_prefix(model, known_prefixes).strip()
    if not requested or model_is_excluded(candidate.excluded_models, requested):
        return False
    folded = requested.casefold()
    leaf = requested.rsplit("/", 1)[-1].casefold()
    if folded in candidate.blocked_models or leaf in candidate.blocked_models:
        return False
    if candidate.models:
        names = {item.strip().casefold() for item in candidate.models if item.strip()}
        return folded in names
    if not candidate.family_fallback or "/" in requested:
        return False
    return _model_family(requested) == credential_provider(candidate.provider)


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

    known_prefixes = _known_credential_prefixes(candidates)
    prefixed = [item for item in candidates if prefix_or_none(item.prefix) and item.weight > 0]
    serving = [item for item in prefixed if candidate_serves_model(item, model, known_prefixes=known_prefixes)]
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
        clock=REAL_CLOCK,
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
        wire_model=rewrite_model_for_credential(model, prefix, known_prefixes=known_prefixes),
        requested_model=model,
        route=route,
        sticky_key=sticky_key if use_sticky else None,
        sticky_kind=sticky_kind if use_sticky else None,
    )
    _remember_selection(choice.account_id)
    return choice, outcome.mutation if use_sticky else None


class CliproxyClaudeRouteRefused(Exception):
    """No CLIProxyAPI credential prefix could be named for a Claude request.

    A plain Claude model name lets CLIProxyAPI pick the credential itself, and
    with its session affinity off it rotates credentials on every request. Each
    rotation lands on an account whose prompt cache is cold, so the whole
    prompt is written to the cache again at twice the input rate. A Claude
    request is refused instead of being sent without its credential prefix.
    """

    def __init__(self, model: str, reason: str) -> None:
        super().__init__(f"no CLIProxyAPI credential prefix for {model}: {reason}")
        self.model = model
        self.reason = reason


def requires_cliproxy_credential_prefix(model: str) -> bool:
    """Whether a request for ``model`` must name its CLIProxyAPI credential.

    Claude only: its prompt cache is per Anthropic account, so a request that
    changes credential pays for a full cache write. The other families keep
    the fail-open behaviour. Matched on the model leaf containing ``claude``,
    wider than the family guess, so an alias such as ``cp-claude-sonnet`` is
    covered too.
    """

    return "claude" in model.rsplit("/", 1)[-1].casefold()


async def apply_cliproxy_account_route(
    body: dict[str, JsonValue],
    *,
    headers: Mapping[str, str] | None = None,
    client: ClaudeSidecarClient | None = None,
    hints: CliproxyStickyHints | None = None,
) -> CliproxyDispatchChoice | None:
    """Rewrite ``body['model']`` when capacity routing can name a credential.

    For a Claude model the rewrite is mandatory: a disabled switch, an
    unconfigured sidecar, no prefixed credential, or a selection failure
    raises ``CliproxyClaudeRouteRefused`` and the body is left unsent. For
    other models those cases leave the model unchanged. Every routed request
    records one ``codex_lb_cliproxy_route_outcome_total`` sample and one
    ``cliproxy_route_outcome`` log line, so a fail-open or refusal is visible.
    """

    _CURRENT_CHOICE.set(None)
    model = body.get("model")
    if not isinstance(model, str) or not model.strip():
        return None
    prefix_required = requires_cliproxy_credential_prefix(model)
    source: CliproxyKeySource = "unknown"
    try:
        settings = await get_settings_cache().get()
        if not _routing_active(settings):
            if prefix_required:
                _record_route_outcome("refused", "disabled", model=model)
                raise CliproxyClaudeRouteRefused(model, "CLIProxyAPI capacity routing is off")
            return None
        identity = _resolve_sticky_identity(
            hints if hints is not None else cliproxy_sticky_hints_from_body(body),
            headers or {},
            sticky_enabled=bool(settings.sticky_threads_enabled),
        )
        source = identity.source
        choice, outage_fail_open = await _select_dispatch(settings, model, client=client, identity=identity)
    except CliproxyClaudeRouteRefused:
        raise
    except Exception as exc:
        if prefix_required:
            logger.warning("cliproxy capacity route failed; refusing the Claude request", exc_info=True)
            _record_route_outcome("refused", source, model=model)
            raise CliproxyClaudeRouteRefused(model, "credential selection failed") from exc
        logger.warning("cliproxy capacity route failed; leaving model unchanged", exc_info=True)
        _record_route_outcome("fail_open", source, model=model)
        return None
    if choice is None:
        if prefix_required and not outage_fail_open:
            _record_route_outcome("refused", source, model=model)
            raise CliproxyClaudeRouteRefused(model, "no prefixed CLIProxyAPI credential serves this model")
        _record_route_outcome("no_candidate", source, model=model)
        return None
    body["model"] = choice.wire_model
    _CURRENT_CHOICE.set(choice)
    _record_route_outcome(_route_outcome(choice), choice.key_source, model=choice.wire_model, choice=choice)
    return choice


async def rebind_cliproxy_account_route(
    body: dict[str, JsonValue],
    *,
    client: ClaudeSidecarClient | None = None,
) -> CliproxyDispatchChoice | None:
    """Serve this request from another credential after a 401, 403 or 429.

    The failed credential cools down for ``_COOLDOWN_SECONDS``. When the
    conversation pin named it before this request, the pin stays and the
    request moves to the conversation's fallback pin, so later turns return
    to the warm account. A pin this request created has no warm cache and
    moves to the new credential.
    """

    current = _CURRENT_CHOICE.get()
    if current is None:
        return None
    _start_cooldown(current.account_id)
    try:
        settings = await get_settings_cache().get()
        if not _routing_active(settings):
            return None
        choice = await _select_rebind(settings, current, client=client)
    except Exception:
        logger.warning("cliproxy capacity rebind failed", exc_info=True)
        _record_route_outcome("fail_open", current.key_source, model=current.requested_model)
        return None
    if choice is None or choice.account_id == current.account_id:
        return None
    rebound = replace(choice, route="rebind")
    body["model"] = rebound.wire_model
    _CURRENT_CHOICE.set(rebound)
    _record_route_outcome("rebind", rebound.key_source, model=rebound.wire_model, choice=rebound)
    return rebound


def cliproxy_sticky_hints(payload: ChatCompletionsRequest, *, api_key_id: str | None) -> CliproxyStickyHints:
    """Read the conversation identity from the client's chat request."""

    extra: Mapping[str, object] = payload.model_extra or {}
    return CliproxyStickyHints(
        prompt_cache_key=_text_or_none(extra.get("prompt_cache_key")) or _text_or_none(extra.get("promptCacheKey")),
        body_session_id=_body_session_id(extra),
        derived_key=_derived_chat_key(
            model=payload.model,
            instructions=payload.instructions,
            messages=payload.messages,
            api_key_id=api_key_id,
        ),
    )


def cliproxy_responses_sticky_hints(
    payload: ResponsesRequest,
    *,
    prompt_cache_key_derived: bool,
) -> CliproxyStickyHints:
    """Read the conversation identity from a Responses request before the chat bridge.

    The chat translation keeps only ``prompt_cache_key``, so the body session
    ids are read here. ``prompt_cache_key_derived`` marks a key the API layer
    derived itself: it still pins the conversation, but below the client's
    session headers and body ids, the way a derived key ranks below explicit
    ids in CLIProxyAPI.
    """

    cache_key = _text_or_none(payload.prompt_cache_key)
    body_session_id = _body_session_id(payload.model_extra or {})
    if prompt_cache_key_derived:
        return CliproxyStickyHints(body_session_id=body_session_id, derived_key=cache_key)
    return CliproxyStickyHints(prompt_cache_key=cache_key, body_session_id=body_session_id)


def cliproxy_sticky_hints_from_body(body: Mapping[str, JsonValue]) -> CliproxyStickyHints:
    """Hints for a caller that only has the forwarded chat body."""

    model = body.get("model")
    return CliproxyStickyHints(
        prompt_cache_key=prompt_cache_key_from_body(body),
        body_session_id=_body_session_id(body),
        derived_key=_derived_chat_key(
            model=model if isinstance(model, str) else None,
            instructions=body.get("instructions"),
            messages=body.get("messages"),
            api_key_id=None,
        ),
    )


def _derived_chat_key(
    *,
    model: str | None,
    instructions: object,
    messages: object,
    api_key_id: str | None,
) -> str | None:
    return derive_content_prompt_cache_key(
        model=model,
        instructions=instructions,
        input_value=messages,
        api_key_id=api_key_id,
    )


def _body_session_id(body: Mapping[str, object]) -> str | None:
    for name in ("session_id", "sessionId"):
        value = _text_or_none(body.get(name))
        if value:
            return value
    metadata = body.get("metadata")
    if isinstance(metadata, Mapping):
        metadata_map = cast(Mapping[str, object], metadata)
        for name in ("session_id", "sessionId"):
            value = _text_or_none(metadata_map.get(name))
            if value:
                return value
    return None


def _text_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


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
        # route_identity is CLIProxyAPI's auth_index, or the same digest computed
        # locally when CLIProxyAPI omits it, so pins survive prefix, model,
        # name, and on/off edits.
        identity = row.route_identity
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
                route_identity=row.route_identity,
            )
        )
    return built


async def _load_candidates(
    settings: DashboardSettings,
    model: str,
    client: ClaudeSidecarClient | None,
    *,
    exclude_account_ids: frozenset[str] = frozenset(),
) -> tuple[list[CliproxyCandidate], bool]:
    """Credentials that can serve this request, and whether this load saw a management outage.

    During an outage the candidates are the last known credentials.

    The management outage state follows only this load's own reads: the stored
    poll snapshot, the API-key listing, and prefix assignment. Any failure keeps
    the outage (and warns once per episode); a load where all of them succeed
    against a healthy snapshot ends it, whatever an earlier request recorded.
    """

    now = datetime.now(timezone.utc)
    stored = _SNAPSHOTS.read(settings.claude_sidecar_quota_state_json)
    snapshot = _routing_snapshot(stored)
    candidates = candidates_from_snapshot(snapshot, now=now)
    failures: list[BaseException] = []
    if client is not None:
        try:
            rows = await _cached_api_keys(client)
        except Exception as exc:
            rows = _LAST_GOOD_API_KEYS
            failures.append(exc)
            logger.info("cliproxy api-key list unavailable; routing the last known api keys", exc_info=True)
        candidates.extend(candidates_from_api_keys(rows))
        candidates = await _attach_discovered_models(candidates, client)
    if exclude_account_ids:
        candidates = [item for item in candidates if item.account_id not in exclude_account_ids]
    filled = await _fill_empty_prefixes(candidates, model, client, failures=failures)
    outage = bool(failures) or _snapshot_read_failed(stored)
    if outage:
        _warn_management_outage(stored, failures, using=filled)
    elif stored is None or stored.status == "healthy":
        _note_management_recovered()
    return filled, outage


def _routing_snapshot(stored: SidecarQuotaSnapshot | None) -> SidecarQuotaSnapshot | None:
    """The snapshot routing should score, keeping accounts across a failed poll.

    A healthy poll replaces the remembered list, including a healthy empty list:
    credentials that were removed must not come back on the next failed poll.
    A failed poll that still carries the previous accounts (the poller keeps them)
    is used as-is. A failed poll that stored no accounts falls back to the last
    snapshot this process saw with accounts, so a worker that has not yet observed
    the retaining poller does not refuse traffic.
    """

    global _LAST_GOOD_SNAPSHOT
    if stored is not None and stored.status == "healthy":
        _LAST_GOOD_SNAPSHOT = stored if stored.accounts else None
        return stored
    if stored is not None and stored.accounts:
        return stored
    if _snapshot_read_failed(stored) and _LAST_GOOD_SNAPSHOT is not None:
        return _LAST_GOOD_SNAPSHOT
    return stored


def _snapshot_read_failed(snapshot: SidecarQuotaSnapshot | None) -> bool:
    return snapshot is not None and snapshot.status in {"unauthorized", "unreachable", "error"}


def _route_params(settings: DashboardSettings) -> _RouteParams:
    return _RouteParams(
        strategy=_routing_strategy(settings),
        prefer_reset=bool(settings.prefer_earlier_reset_accounts),
        reset_window=_reset_window(settings),
        max_age=cliproxy_sticky_max_age_seconds(settings),
        primary_budget=_primary_budget(settings),
        secondary_budget=_secondary_budget(settings),
    )


async def _select_dispatch(
    settings: DashboardSettings,
    model: str,
    *,
    client: ClaudeSidecarClient | None,
    identity: _StickyIdentity,
) -> tuple[CliproxyDispatchChoice | None, bool]:
    """The chosen credential, and whether an outage lets CLIProxyAPI choose instead.

    The second value is only meaningful when no credential was chosen. It is
    decided from the same candidates selection used, model catalog included.
    """

    candidates, outage = await _load_candidates(settings, model, client)
    params = _route_params(settings)
    usable = _without_cooling(candidates, model)
    if identity.key is None or identity.kind is None:
        choice, _mutation = await choose_cliproxy_route(
            usable,
            model=model,
            sticky_key=None,
            sticky_kind=None,
            sticky_repo=None,
            sticky_enabled=False,
            routing_strategy=params.strategy,
            prefer_earlier_reset=params.prefer_reset,
            prefer_earlier_reset_window=params.reset_window,
        )
        if choice is None:
            _warn_no_candidate(candidates, model)
            return None, _management_outage_fail_open(candidates, model, outage=outage)
        return replace(choice, key_source=identity.source), False
    async with get_background_session() as session:
        repo = _CliproxyStickyRepository(session)
        choice = await _route_pinned(repo, candidates, usable, model=model, identity=identity, params=params)
    if choice is None:
        _warn_no_candidate(candidates, model)
        return None, _management_outage_fail_open(candidates, model, outage=outage)
    return choice, False


async def _route_pinned(
    repo: _CliproxyStickyRepository,
    candidates: list[CliproxyCandidate],
    usable: list[CliproxyCandidate],
    *,
    model: str,
    identity: _StickyIdentity,
    params: _RouteParams,
) -> CliproxyDispatchChoice | None:
    """Route one request of a conversation that has a sticky key.

    A pin on a credential that is cooling down after a 401/403/429, or that
    the shared selection skips without moving the pin, is kept. The request
    is served from the conversation's fallback pin instead, so the detour
    also stays on one credential.
    """

    assert identity.key is not None and identity.kind is not None
    key, kind = identity.key, identity.kind
    existing_id, _deadline = await repo.lookup(key, kind=kind, max_age_seconds=params.max_age)
    if existing_id is not None and existing_id in _cooling_ids() and _pin_still_usable(candidates, existing_id, model):
        fallback = await _route_fallback(
            repo, usable, model=model, identity=identity, params=params, pinned=existing_id
        )
        if fallback is not None:
            return fallback
        # Nothing else can serve: the cooling pin still beats failing.
        pool = candidates
    elif existing_id is not None:
        pool = _without_cooling(candidates, model, keep=existing_id)
    else:
        pool = usable
    claim = await _claim_route(repo, pool, model=model, key=key, kind=kind, params=params)
    if claim.choice is None:
        return None
    choice = replace(claim.choice, key_source=identity.source)
    pinned = claim.observed_account_id
    if pinned is not None and pinned != choice.account_id and claim.mutation is None:
        # The shared selection served another credential and kept the pin
        # (a rate-limited pin waiting for its reset).
        fallback = await _route_fallback(repo, usable, model=model, identity=identity, params=params, pinned=pinned)
        if fallback is not None:
            return fallback
    return choice


async def _route_fallback(
    repo: _CliproxyStickyRepository,
    candidates: Sequence[CliproxyCandidate],
    *,
    model: str,
    identity: _StickyIdentity,
    params: _RouteParams,
    pinned: str,
    exclude: frozenset[str] = frozenset(),
) -> CliproxyDispatchChoice | None:
    assert identity.key is not None and identity.kind is not None
    pool = [item for item in candidates if item.account_id != pinned and item.account_id not in exclude]
    claim = await _claim_route(
        repo,
        pool,
        model=model,
        key=_fallback_key(identity.key),
        kind=identity.kind,
        params=params,
    )
    if claim.choice is None:
        return None
    return replace(
        claim.choice,
        route="rebind",
        sticky_key=identity.key,
        sticky_kind=identity.kind,
        key_source=identity.source,
        fallback=True,
    )


@dataclass(frozen=True, slots=True)
class _Claim:
    choice: CliproxyDispatchChoice | None
    mutation: _StickyMutation | None
    # The pin the final selection started from.
    observed_account_id: str | None


async def _claim_route(
    repo: _CliproxyStickyRepository,
    candidates: Sequence[CliproxyCandidate],
    *,
    model: str,
    key: str,
    kind: StickySessionKind,
    params: _RouteParams,
) -> _Claim:
    """Choose a credential for ``key`` and write the pin with compare-and-set.

    A write applies only while the row still names the account this request
    read, names the account it chose, or has expired. When a concurrent
    request wrote first, this request re-reads that pin and routes there.
    CLIProxyAPI gets the same insert-if-absent result from its in-process
    session cache; the conditional upsert makes it hold across workers.
    """

    claim = _Claim(None, None, None)
    for _attempt in range(_CLAIM_ATTEMPTS):
        existing_id, deadline = await repo.lookup(key, kind=kind, max_age_seconds=params.max_age)
        choice, mutation = await choose_cliproxy_route(
            candidates,
            model=model,
            sticky_key=key,
            sticky_kind=kind,
            sticky_repo=cast(StickySessionsRepository, repo),
            sticky_enabled=True,
            existing_account_id=existing_id,
            refresh_skip_deadline=deadline,
            routing_strategy=params.strategy,
            prefer_earlier_reset=params.prefer_reset,
            prefer_earlier_reset_window=params.reset_window,
            sticky_max_age_seconds=params.max_age,
            budget_threshold_pct=params.primary_budget,
            secondary_budget_threshold_pct=params.secondary_budget,
        )
        claim = _Claim(choice, mutation, existing_id)
        if await _apply_sticky_mutation(
            repo,
            key,
            kind,
            mutation,
            expected_account_id=existing_id,
            max_age_seconds=params.max_age,
        ):
            return claim
        logger.info("cliproxy sticky pin changed concurrently; following the winner key_kind=%s", kind.value)
    logger.warning("cliproxy sticky pin kept changing; serving without a pin write key_kind=%s", kind.value)
    return _Claim(claim.choice, None, None)


async def _select_rebind(
    settings: DashboardSettings,
    current: CliproxyDispatchChoice,
    *,
    client: ClaudeSidecarClient | None,
) -> CliproxyDispatchChoice | None:
    model = current.requested_model
    failed = frozenset({current.account_id})
    candidates, _outage = await _load_candidates(settings, model, client, exclude_account_ids=failed)
    usable = _without_cooling(candidates, model)
    params = _route_params(settings)
    identity = _StickyIdentity(current.sticky_key, current.sticky_kind, current.key_source)
    if identity.key is None or identity.kind is None:
        choice, _mutation = await choose_cliproxy_route(
            usable,
            model=model,
            sticky_key=None,
            sticky_kind=None,
            sticky_repo=None,
            sticky_enabled=False,
            routing_strategy=params.strategy,
            prefer_earlier_reset=params.prefer_reset,
            prefer_earlier_reset_window=params.reset_window,
        )
        return replace(choice, key_source=identity.source) if choice is not None else None
    async with get_background_session() as session:
        repo = _CliproxyStickyRepository(session)
        if current.fallback or current.route == "sticky":
            # The pin named a credential that served this conversation before.
            # Keep it; the fallback pin carries the conversation meanwhile.
            pinned = await repo.get_account_id(identity.key, kind=identity.kind, max_age_seconds=params.max_age)
            return await _route_fallback(
                repo,
                usable,
                model=model,
                identity=identity,
                params=params,
                pinned=pinned or current.account_id,
                exclude=failed,
            )
        # This request created the pin, so no warm cache is lost by moving it.
        claim = await _claim_route(
            repo,
            usable,
            model=model,
            key=identity.key,
            kind=identity.kind,
            params=params,
        )
    return replace(claim.choice, key_source=identity.source) if claim.choice is not None else None


def _resolve_sticky_identity(
    hints: CliproxyStickyHints,
    headers: Mapping[str, str],
    *,
    sticky_enabled: bool,
) -> _StickyIdentity:
    """Pick the conversation identity, strongest client signal first.

    The client's ``prompt_cache_key`` and the Codex headers keep their place.
    Then come the session headers and body fields CLIProxyAPI's
    ``ExtractSessionID`` and LiteLLM's ``session_affinity`` read, and last a
    key derived from the conversation content.
    """

    if not sticky_enabled:
        return _StickyIdentity(None, None, "disabled")
    if hints.prompt_cache_key:
        return _StickyIdentity(
            f"cliproxy:prompt_cache:{hints.prompt_cache_key}",
            StickySessionKind.PROMPT_CACHE,
            "prompt_cache_key",
            hints.prompt_cache_key,
        )
    turn_state = _sticky_key_from_turn_state_header(headers)
    if turn_state and not turn_state.startswith(("turn_", "http_turn_")):
        return _StickyIdentity(
            f"cliproxy:turn:{turn_state}",
            StickySessionKind.STICKY_THREAD,
            "turn_state",
            turn_state,
        )
    session_key = _sticky_key_from_session_header(headers) or _client_session_header(headers)
    if session_key:
        return _StickyIdentity(
            f"cliproxy:session:{session_key}",
            StickySessionKind.STICKY_THREAD,
            "session_header",
            session_key,
        )
    if hints.body_session_id:
        body_session_id = _bounded_identity(hints.body_session_id)
        return _StickyIdentity(
            f"cliproxy:session:{body_session_id}",
            StickySessionKind.STICKY_THREAD,
            "body_session_id",
            body_session_id,
        )
    if hints.derived_key:
        return _StickyIdentity(
            f"cliproxy:derived:{hints.derived_key}",
            StickySessionKind.PROMPT_CACHE,
            "derived",
            hints.derived_key,
        )
    return _StickyIdentity(None, None, "none")


def cliproxy_conversation_id(hints: CliproxyStickyHints, headers: Mapping[str, str]) -> str | None:
    """The conversation id the sticky pin is keyed on, without its namespace.

    Read in the same order as the pin, so a caller that forwards it as
    ``prompt_cache_key`` gives CLIProxyAPI and xAI the id codex-lb pins on.
    It is read even when sticky routing is off: the upstream cache still
    needs a stable id when codex-lb itself does not pin.
    """

    return _resolve_sticky_identity(hints, headers, sticky_enabled=True).value


def _sticky_identity_from_request(
    *,
    model_body_key: str | None,
    headers: Mapping[str, str],
    sticky_enabled: bool,
) -> tuple[str | None, StickySessionKind | None]:
    identity = _resolve_sticky_identity(
        CliproxyStickyHints(prompt_cache_key=_text_or_none(model_body_key)),
        headers,
        sticky_enabled=sticky_enabled,
    )
    return identity.key, identity.kind


def _client_session_header(headers: Mapping[str, str]) -> str | None:
    normalized = {key.lower(): value for key, value in headers.items()}
    for name in _CLIENT_SESSION_HEADERS:
        value = _text_or_none(normalized.get(name))
        if value:
            return _bounded_identity(value)
    for name in sorted(normalized):
        if not _VENDOR_SESSION_HEADER.match(name):
            continue
        value = _text_or_none(normalized.get(name))
        if value:
            return _bounded_identity(value)
    return None


def _bounded_identity(value: str) -> str:
    """Keep a client id as the key unless it is too long for one."""

    if len(value) <= _IDENTITY_MAX_CHARS:
        return value
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _fallback_key(key: str) -> str:
    return _FALLBACK_KEY_PREFIX + hashlib.sha256(key.encode()).hexdigest()


def _pin_still_usable(candidates: Sequence[CliproxyCandidate], account_id: str, model: str) -> bool:
    """Whether a cooling pin is worth keeping until its cooldown ends.

    A pin that no longer serves the model, or whose credential is
    quota-exhausted, paused or needs re-auth, has nothing to return to. The
    normal selection moves it instead.
    """

    pinned = next((item for item in _serving_candidates(candidates, model) if item.account_id == account_id), None)
    return pinned is not None and pinned.state.status not in _UNUSABLE_PIN_STATUSES


def _start_cooldown(account_id: str) -> None:
    _COOLING[account_id] = time.monotonic() + _COOLDOWN_SECONDS


def _cooling_ids() -> frozenset[str]:
    now = time.monotonic()
    for account_id in [item for item, until in _COOLING.items() if until <= now]:
        _COOLING.pop(account_id, None)
    return frozenset(_COOLING)


def forget_cooldowns() -> None:
    _COOLING.clear()


def _without_cooling(
    candidates: list[CliproxyCandidate],
    model: str,
    *,
    keep: str | None = None,
) -> list[CliproxyCandidate]:
    """Skip cooling credentials unless no other credential can take ``model``.

    ``keep`` names the conversation's pin, which stays eligible. A spare
    counts only if the balancer would select it: one that is paused,
    exhausted or needs re-auth leaves the cooling credential as the last
    resort instead of failing the request open.
    """

    cooling = _cooling_ids() - {keep}
    if not cooling:
        return candidates
    remaining = [item for item in candidates if item.account_id not in cooling]
    return remaining if _selectable(remaining, model) else candidates


def _selectable(candidates: Sequence[CliproxyCandidate], model: str) -> bool:
    """Whether the shared selection would pick any of ``candidates`` for ``model``."""

    states = [_ranked_state(item) for item in _serving_candidates(candidates, model)]
    return bool(states) and select_account(states).account is not None


def _serving_candidates(candidates: Sequence[CliproxyCandidate], model: str) -> list[CliproxyCandidate]:
    known_prefixes = _known_credential_prefixes(candidates)
    return [
        item
        for item in candidates
        if prefix_or_none(item.prefix)
        and item.weight > 0
        and candidate_serves_model(item, model, known_prefixes=known_prefixes)
    ]


def _route_outcome(choice: CliproxyDispatchChoice) -> CliproxyRouteOutcome:
    if choice.sticky_key is None:
        return "unpinned_no_key"
    return choice.route


def _record_route_outcome(
    outcome: CliproxyRouteOutcome,
    key_source: CliproxyKeySource,
    *,
    model: str,
    choice: CliproxyDispatchChoice | None = None,
) -> None:
    if cliproxy_route_outcome_total is not None:
        cliproxy_route_outcome_total.labels(outcome=outcome, key_source=key_source).inc()
    if choice is None:
        logger.warning("cliproxy_route_outcome outcome=%s key_source=%s model=%s", outcome, key_source, model)
        return
    logger.info(
        "cliproxy_route_outcome outcome=%s key_source=%s route=%s provider=%s auth_index=%s model=%s",
        outcome,
        key_source,
        choice.route,
        choice.provider,
        choice.auth_index,
        model,
    )


def record_claude_sticky_cache_result(*, input_tokens: int, cached_input_tokens: int) -> None:
    """Count whether a Claude turn on its conversation's pin read the prompt cache.

    Only a turn served by the credential its conversation was already pinned
    to counts, with a prompt long enough to cache on every Claude model. Such
    a turn repeats a prefix that same Anthropic account cached on an earlier
    turn, so a read of zero means the cache was lost on the way: something
    between CLIProxyAPI and ``api.anthropic.com`` rewrote the body, or the
    body itself changed between turns. A conversation idle past the cache TTL
    also misses once, so the signal is a sustained miss rate, not one miss.
    """

    choice = _CURRENT_CHOICE.get()
    if (
        choice is None
        or choice.route != "sticky"
        or choice.fallback
        or not requires_cliproxy_credential_prefix(choice.requested_model)
        or input_tokens < CLAUDE_CACHEABLE_PROMPT_TOKENS
    ):
        return
    hit = cached_input_tokens > 0
    if cliproxy_claude_sticky_cache_total is not None:
        cliproxy_claude_sticky_cache_total.labels(result="hit" if hit else "miss").inc()
    if not hit:
        _warn_sticky_cache_miss(choice, input_tokens=input_tokens)


def _warn_sticky_cache_miss(choice: CliproxyDispatchChoice, *, input_tokens: int) -> None:
    """Warn, at most once every ten minutes per credential, of a pinned cache miss."""

    now = time.monotonic()
    last = _CACHE_MISS_WARNED.get(choice.account_id)
    if last is not None and now - last < _CACHE_MISS_WARN_SECONDS:
        return
    _CACHE_MISS_WARNED[choice.account_id] = now
    _CACHE_MISS_WARNED.move_to_end(choice.account_id)
    while len(_CACHE_MISS_WARNED) > _NO_CANDIDATE_WARN_LIMIT:
        _CACHE_MISS_WARNED.popitem(last=False)
    logger.warning(
        "cliproxy_claude_sticky_cache_miss provider=%s auth_index=%s model=%s input_tokens=%s: a pinned "
        "Claude conversation read nothing from the prompt cache. CLIProxyAPI must reach api.anthropic.com "
        "directly; a gateway that rewrites the request body in between makes every turn a full cache write",
        choice.provider,
        choice.auth_index,
        choice.wire_model,
        input_tokens,
    )


def _warn_management_outage(
    snapshot: SidecarQuotaSnapshot | None,
    failures: Sequence[BaseException],
    *,
    using: Sequence[CliproxyCandidate],
) -> None:
    """Warn once per outage stretch that routing is on the last known credentials.

    A management 401, 403, timeout, or 5xx must not become a per-request refusal.
    The status in the message is the poll snapshot status, or the live read's
    HTTP status when the API-key listing is what failed.
    """

    global _MANAGEMENT_OUTAGE
    status = _management_status(snapshot, failures)
    now = time.monotonic()
    current = _MANAGEMENT_OUTAGE
    if current is not None and current[0] == status and now - current[1] < _MANAGEMENT_OUTAGE_WARN_SECONDS:
        return
    _MANAGEMENT_OUTAGE = (status, now)
    logger.warning(
        "CLIProxyAPI management unreachable: %s; routing on last known credentials (%s)",
        status,
        len(using),
    )


def _management_status(snapshot: SidecarQuotaSnapshot | None, failures: Sequence[BaseException]) -> str:
    if snapshot is not None and snapshot.status in {"unauthorized", "unreachable", "error"}:
        detail = (snapshot.message or "").strip()
        if snapshot.status == "unauthorized" and "ban" in detail.casefold():
            return "403 IP banned"
        if detail:
            return f"{snapshot.status}: {detail}"
        code = _failure_status_code(failures)
        if code is not None:
            return f"{code} {snapshot.status}"
        return snapshot.status
    code = _failure_status_code(failures)
    if code is not None:
        if code == 403 and any("ban" in str(item).casefold() for item in failures):
            return "403 IP banned"
        return str(code)
    if failures:
        return type(failures[0]).__name__
    return "unreachable"


def _failure_status_code(failures: Sequence[BaseException]) -> int | None:
    for exc in failures:
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int):
            return status_code
    return None


def _note_management_recovered() -> None:
    global _MANAGEMENT_OUTAGE
    _MANAGEMENT_OUTAGE = None


def _management_outage_fail_open(
    candidates: Sequence[CliproxyCandidate],
    model: str,
    *,
    outage: bool,
) -> bool:
    """Whether a Claude request with no prefixed route may go out unprefixed.

    A missing prefix is normally a hard refusal: an unprefixed Claude request
    lets CLIProxyAPI rotate credentials and rewrite the prompt cache. While this
    load's management reads are failing, a last known credential that serves
    the model but could not get a prefix is still better served by CLIProxyAPI
    than refused.

    ``candidates`` are the ones selection just scored, with the discovered model
    catalog attached, so a model the catalog does not serve is refused here too.
    Nothing known that serves the model (cold start, or a healthy empty listing
    that removed the credentials) is refused. So is any request that an
    unprefixed send could land on a credential the operator kept out of
    routing: a known credential that serves the model with a weight of zero or
    less, or one whose captain-set exclusion or quota block covers the model.
    """

    if not outage:
        return False
    known_prefixes = _known_credential_prefixes(candidates)
    serving = [item for item in candidates if candidate_serves_model(item, model, known_prefixes=known_prefixes)]
    if not serving or any(item.weight <= 0 for item in serving):
        return False
    return not any(_restricts_model(item, model, known_prefixes=known_prefixes) for item in candidates)


def _restricts_model(candidate: CliproxyCandidate, model: str, *, known_prefixes: Sequence[str]) -> bool:
    requested = _model_without_known_prefix(model, known_prefixes).strip()
    if not requested:
        return False
    folded = requested.casefold()
    leaf = requested.rsplit("/", 1)[-1].casefold()
    return (
        model_is_excluded(candidate.excluded_models, requested)
        or folded in candidate.blocked_models
        or leaf in candidate.blocked_models
    )


def _warn_no_candidate(candidates: Sequence[CliproxyCandidate], model: str) -> None:
    """Warn, at most once a minute per model, that no prefixed credential serves it."""

    now = time.monotonic()
    folded = model.strip().casefold()
    last = _NO_CANDIDATE_WARNED.get(folded)
    if last is not None and now - last < _NO_CANDIDATE_WARN_SECONDS:
        return
    _NO_CANDIDATE_WARNED[folded] = now
    _NO_CANDIDATE_WARNED.move_to_end(folded)
    while len(_NO_CANDIDATE_WARNED) > _NO_CANDIDATE_WARN_LIMIT:
        _NO_CANDIDATE_WARNED.popitem(last=False)
    prefixed = [item for item in candidates if prefix_or_none(item.prefix)]
    consequence = (
        "the request is refused"
        if requires_cliproxy_credential_prefix(model)
        else "CLIProxyAPI selects the credential itself"
    )
    logger.warning(
        "cliproxy capacity routing found no prefixed credential for model=%s credentials=%s prefixed=%s; %s",
        model,
        len(candidates),
        len(prefixed),
        consequence,
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
    state = replace(
        candidate.state,
        capacity_credits=float(candidate.weight),
        last_selected_at=_LAST_SELECTED.get(candidate.account_id),
    )
    if state.status == AccountStatus.REAUTH_REQUIRED and state.access_token_expires_at is None:
        # The shared selection keeps a reauth-required Codex account routable
        # until its stored access token is known to expire. A CLIProxyAPI
        # credential has no token on this side: CLIProxyAPI reporting it
        # unauthorized means it cannot serve, so it is treated as expired.
        state = replace(state, access_token_expires_at=0.0)
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
    global _API_KEY_CACHE, _LAST_GOOD_API_KEYS
    now = datetime.now(timezone.utc).timestamp()
    cached = _API_KEY_CACHE
    if cached is not None and now - cached[0] < _API_KEY_CACHE_SECONDS:
        return cached[1]
    rows = tuple(await list_routing_api_keys(client))
    _API_KEY_CACHE = (now, rows)
    _LAST_GOOD_API_KEYS = rows
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


def _known_credential_prefixes(candidates: Sequence[CliproxyCandidate]) -> tuple[str, ...]:
    found: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        prefix = prefix_or_none(item.prefix)
        if prefix is None:
            continue
        folded = prefix.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        found.append(prefix)
    return tuple(found)


def _remember_selection(account_id: str) -> None:
    _LAST_SELECTED[account_id] = time.time()
    _LAST_SELECTED.move_to_end(account_id)
    while len(_LAST_SELECTED) > _LAST_SELECTED_LIMIT:
        _LAST_SELECTED.popitem(last=False)


def forget_remembered_prefixes() -> None:
    """Drop prefixes this process stored after an operator changes one.

    The quota snapshot can still show an empty prefix. Forgetting the overlay
    sends the next request through the locked management read, which sees the
    prefix just written.
    """

    _PREFIX_OVERLAY.clear()


def _remember_prefix(account_id: str, prefix: str) -> None:
    cleaned = prefix_or_none(prefix)
    if cleaned is None:
        return
    _PREFIX_OVERLAY[account_id] = (time.monotonic(), cleaned)
    _PREFIX_OVERLAY.move_to_end(account_id)
    while len(_PREFIX_OVERLAY) > _PREFIX_OVERLAY_LIMIT:
        _PREFIX_OVERLAY.popitem(last=False)


def _remembered_prefix(account_id: str) -> str | None:
    remembered = _PREFIX_OVERLAY.get(account_id)
    if remembered is None:
        return None
    stored_at, prefix = remembered
    if time.monotonic() - stored_at > _PREFIX_OVERLAY_SECONDS:
        _PREFIX_OVERLAY.pop(account_id, None)
        return None
    _PREFIX_OVERLAY.move_to_end(account_id)
    return prefix


def _with_remembered_prefixes(candidates: list[CliproxyCandidate]) -> list[CliproxyCandidate]:
    """Fill empty snapshot prefixes from assignments this process already stored.

    API-key account ids use ``route_identity`` (the credential's auth index),
    never a list index, so a list deletion cannot reuse a neighbor's remembered
    prefix.
    """

    updated: list[CliproxyCandidate] = []
    for item in candidates:
        if prefix_or_none(item.prefix) is not None:
            updated.append(item)
            continue
        remembered = _remembered_prefix(item.account_id)
        if remembered is None:
            updated.append(item)
            continue
        updated.append(replace(item, prefix=remembered))
    return updated


async def _stored_prefixes(
    client: ClaudeSidecarClient,
) -> tuple[dict[str, str], dict[str, str], set[str]]:
    """Prefixes currently stored, read while the prefix lock is held.

    API-key prefixes are keyed by route identity, not list index. A deletion
    that shifts the list cannot hand one entry's prefix to its neighbor.

    CLIProxyAPI's auth-files listing omits ``prefix``, so an OAuth prefix is
    read from the auth file itself. Without that read every stored prefix
    looks empty and is written again whenever the remembered prefix expires.
    """

    oauth = await asyncio.to_thread(_oauth_prefixes, await client.list_auth_files())
    api: dict[str, str] = {}
    for row in await list_routing_api_keys(client):
        prefix = prefix_or_none(row.prefix)
        if prefix and row.route_identity:
            api[row.route_identity] = prefix
    taken = {prefix.casefold() for prefix in oauth.values()}
    taken.update(prefix.casefold() for prefix in api.values())
    return oauth, api, taken


def _oauth_prefixes(entries: Sequence[Mapping[str, JsonValue]]) -> dict[str, str]:
    """Map each listed auth-file name to the routable prefix stored for it.

    A name whose prefix is empty or not routable, or whose auth file cannot be
    read, is left out and gets a generated prefix, as before this read existed.
    """

    prefixes: dict[str, str] = {}
    for entry in entries:
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        prefix = prefix_or_none(stored_prefix_for_entry(entry))
        if prefix:
            prefixes[name.strip()] = prefix
    return prefixes


def _known_prefix(
    candidate: CliproxyCandidate,
    oauth_prefixes: Mapping[str, str],
    api_prefixes: Mapping[str, str],
) -> str | None:
    if candidate.api_key_kind is not None:
        if not candidate.route_identity:
            return None
        return api_prefixes.get(candidate.route_identity)
    if not candidate.name:
        return None
    return oauth_prefixes.get(candidate.name)


async def _fill_empty_prefixes(
    candidates: list[CliproxyCandidate],
    model: str,
    client: ClaudeSidecarClient | None,
    *,
    failures: list[BaseException] | None = None,
) -> list[CliproxyCandidate]:
    """Give each unprefixed candidate that serves ``model`` its stored or a new prefix.

    A management failure leaves the candidates as they are and is appended to
    ``failures``, so the caller keeps the outage for this load.
    """

    if client is None:
        return candidates
    candidates = _with_remembered_prefixes(candidates)
    known_prefixes = _known_credential_prefixes(candidates)
    needing = [
        item
        for item in candidates
        if prefix_or_none(item.prefix) is None
        and item.weight > 0
        and candidate_serves_model(item, model, known_prefixes=known_prefixes)
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
                        # Already stored: reuse it and send no write, not
                        # even one carrying the same value.
                        assigned[item.account_id] = existing
                        taken.add(existing.casefold())
                        _remember_prefix(item.account_id, existing)
                        continue
                    prefix = generated_prefix(item.provider, item.account_id, taken)
                    stored = await _store_prefix_if_empty(client, session, item, prefix)
                    if stored:
                        assigned[item.account_id] = stored
                        taken.add(stored.casefold())
                        _remember_prefix(item.account_id, stored)
    except Exception as exc:
        logger.info("cliproxy prefix assignment failed; unprefixed credentials stay unpinned", exc_info=True)
        if failures is not None:
            failures.append(exc)
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
    if candidate.api_key_kind is not None:
        if not candidate.route_identity:
            return None
        async with cliproxy_api_key_list_lock(session, candidate.api_key_kind):
            return await set_api_key_prefix_if_empty(
                client,
                kind_slug=candidate.api_key_kind,
                route_identity=candidate.route_identity,
                prefix=prefix,
            )
    if not candidate.name:
        return None
    await client.patch_auth_file_fields(candidate.name, {"prefix": prefix})
    return prefix


class _CliproxyStickyRepository:
    """Sticky pins for credential ids that are not ``accounts`` rows."""

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
        """Read the live pin, bypassing the session cache.

        A compare-and-set retry must see the row another worker just wrote.
        """

        if kind == StickySessionKind.CODEX_SESSION:
            return None, None
        statement = (
            select(CliproxyStickySession)
            .where(CliproxyStickySession.key == key, CliproxyStickySession.kind == kind.value)
            .execution_options(populate_existing=True)
        )
        row = (await self._session.execute(statement)).scalar_one_or_none()
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

    async def claim(
        self,
        key: str,
        account_id: str,
        kind: StickySessionKind,
        *,
        expected_account_id: str | None,
        max_age_seconds: int | None,
    ) -> bool:
        """Write the pin unless another request changed it since this one read it.

        The write applies when the row is absent, still names
        ``expected_account_id``, already names ``account_id``, or has expired.
        Returns whether the row now names ``account_id``.
        """

        if kind == StickySessionKind.CODEX_SESSION:
            return True
        dialect = self._session.get_bind().dialect.name
        if dialect not in {"postgresql", "sqlite"}:
            raise RuntimeError(f"CLIProxy sticky upsert unsupported for dialect={dialect!r}")
        insert_fn = pg_insert if dialect == "postgresql" else sqlite_insert
        now = datetime.now(timezone.utc)
        owners = [account_id] if expected_account_id is None else [expected_account_id, account_id]
        conditions = [CliproxyStickySession.account_id.in_(owners)]
        if max_age_seconds is not None:
            stale_before = to_utc_naive(now - timedelta(seconds=max_age_seconds))
            conditions.append(CliproxyStickySession.updated_at < stale_before)
        statement = insert_fn(CliproxyStickySession).values(
            key=key,
            kind=kind.value,
            account_id=account_id,
            updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[CliproxyStickySession.key, CliproxyStickySession.kind],
            set_={"account_id": account_id, "updated_at": now},
            where=or_(*conditions),
        ).returning(CliproxyStickySession.account_id)
        async with sqlite_writer_section():
            written = (await self._session.execute(statement)).scalar_one_or_none()
            await self._session.commit()
        return written == account_id

    async def release(self, key: str, kind: StickySessionKind, *, expected_account_id: str | None) -> None:
        """Delete the pin only while it still names the account this request read."""

        if expected_account_id is None:
            return
        statement = delete(CliproxyStickySession).where(
            CliproxyStickySession.key == key,
            CliproxyStickySession.kind == kind.value,
            CliproxyStickySession.account_id == expected_account_id,
        )
        async with sqlite_writer_section():
            await self._session.execute(statement)
            await self._session.commit()


async def _apply_sticky_mutation(
    repo: _CliproxyStickyRepository,
    key: str | None,
    kind: StickySessionKind | None,
    mutation: _StickyMutation | None,
    *,
    expected_account_id: str | None,
    max_age_seconds: int | None,
) -> bool:
    """Persist the selection's pin change; ``False`` when a concurrent write won."""

    if key is None or kind is None or mutation is None:
        return True
    if mutation.account_id is None:
        await repo.release(key, kind, expected_account_id=expected_account_id)
        return True
    if _sticky_refresh_write_skippable(mutation, initialize_seed_key=None):
        return True
    return await repo.claim(
        key,
        mutation.account_id,
        kind,
        expected_account_id=expected_account_id,
        max_age_seconds=max_age_seconds,
    )


def _refresh_skip_deadline(updated_at: datetime, *, now: datetime, max_age_seconds: int) -> datetime | None:
    age_seconds = (now - updated_at).total_seconds()
    if age_seconds < 0:
        return None
    skip_window_seconds = min(_REFRESH_SKIP_MAX_SECONDS, max_age_seconds * _REFRESH_SKIP_TTL_FRACTION)
    if age_seconds > skip_window_seconds:
        return None
    return updated_at + timedelta(seconds=skip_window_seconds)
