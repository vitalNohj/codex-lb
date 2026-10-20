from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping
from app.modules.claude_sidecar.auth_file import default_auth_dir, stored_prefix_for_entry
from app.modules.claude_sidecar.excluded_models import (
    excluded_models_for_entry,
    normalize_excluded_models,
)

logger = logging.getLogger(__name__)

SidecarQuotaStatus = Literal["healthy", "unauthorized", "unreachable", "error", "unknown"]


@dataclass(frozen=True, slots=True)
class SidecarModelQuota:
    model: str
    quota_exceeded: bool
    next_recover_at: datetime | None


@dataclass(frozen=True, slots=True)
class SidecarOAuthUsageBucket:
    remaining_percent: float | None
    resets_at: datetime | None


@dataclass(frozen=True, slots=True)
class SidecarOAuthUsage:
    five_hour: SidecarOAuthUsageBucket | None
    seven_day: SidecarOAuthUsageBucket | None


@dataclass(frozen=True, slots=True)
class GrokCreditWindow:
    """One Grok consumer quota window, in quota-axi's normalized shape."""

    id: str
    label: str
    kind: str
    percent_used: float
    percent_remaining: float
    starts_at: datetime | None = None
    resets_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class GrokTokenRollup:
    """Tokens this process has seen for one xAI auth inside the current window."""

    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    request_count: int = 0
    window_start: datetime | None = None


@dataclass(frozen=True, slots=True)
class GrokCreditsQuota:
    """Parsed GetGrokCreditsConfig plus a usage-queue token rollup.

    ``observed_limit`` is set only for the poll that just saw a 429. It is not
    stored, so a later poll does not treat an old signal as a new one.
    """

    windows: tuple[GrokCreditWindow, ...] = ()
    prepaid_credits: int | None = None
    refreshed_at: datetime | None = None
    token_rollup: GrokTokenRollup | None = None
    observed_limit: str | None = None


@dataclass(frozen=True, slots=True)
class SidecarAuthQuota:
    name: str
    auth_index: str | None
    email: str | None
    status: str | None
    status_message: str | None
    disabled: bool
    unavailable: bool
    quota_exceeded: bool
    next_recover_at: datetime | None
    model_states: tuple[SidecarModelQuota, ...]
    success: int
    failed: int
    last_refresh: datetime | None
    credential_path: str | None = None
    oauth_usage: SidecarOAuthUsage | None = None
    provider: str | None = None
    expired: datetime | None = None
    excluded_models: tuple[str, ...] = ()
    excluded_models_available: bool = False
    prefix: str | None = None
    grok_credits: GrokCreditsQuota | None = None
    # CLIProxyAPI selection controls. Missing weight is 1; missing priority is 0.
    weight: int | None = None
    priority: int | None = None


def credential_provider(value: str | None) -> str:
    """Return the hold/account provider, treating a missing value as Claude.

    Snapshots written before provider tags existed omit the field. Those rows
    are Claude holds and must keep matching Claude accounts.
    """

    text = (value or "").strip().lower()
    return text or "claude"


def claude_quota_snapshot(snapshot: SidecarQuotaSnapshot) -> SidecarQuotaSnapshot:
    """Return the Claude rows of a mixed snapshot.

    xAI credentials share the stored snapshot once their poll is enabled. Claude
    quota, estimates, and the Claude account card keep reading only Claude rows,
    which is every row while that poll is off.
    """

    accounts = tuple(account for account in snapshot.accounts if credential_provider(account.provider) == "claude")
    holds = tuple(hold for hold in snapshot.rate_limit_holds if credential_provider(hold.provider) == "claude")
    if len(accounts) == len(snapshot.accounts) and len(holds) == len(snapshot.rate_limit_holds):
        return snapshot
    return replace(snapshot, accounts=accounts, rate_limit_holds=holds)


@dataclass(frozen=True, slots=True)
class SidecarRateLimitHold:
    """A pause this poller owns for one CLIProxyAPI auth file.

    ``released`` is set when an operator resumes that auth before ``until``.
    The next poll must not disable the auth again while the exhausted window
    still ends at that same instant.

    ``provider`` keeps an xAI hold from disabling a Claude auth that happens to
    share a file name, and the reverse. ``kind`` is ``free-usage-exhausted`` or
    ``backoff`` for xAI; Claude window holds leave it unset. ``backoff_level``
    is the conductor quota backoff step for a generic xAI 429.
    """

    name: str
    until: datetime
    released: bool
    provider: str = "claude"
    kind: str | None = None
    backoff_level: int = 0


@dataclass(frozen=True, slots=True)
class SidecarQuotaSnapshot:
    checked_at: datetime
    status: SidecarQuotaStatus
    message: str | None
    accounts: tuple[SidecarAuthQuota, ...] = field(default_factory=tuple)
    rate_limit_holds: tuple[SidecarRateLimitHold, ...] = ()


def parse_auth_files(
    raw: Iterable[Mapping[str, JsonValue]],
    *,
    auth_dir: Path | None = None,
    provider: str | None = "claude",
) -> list[SidecarAuthQuota]:
    """Parse management auth-file entries for one provider.

    ``provider="claude"`` (the default) keeps the historical Claude filter,
    including ``account_type=anthropic``. ``provider=None`` keeps every entry.
    Any other provider matches ``provider`` / ``type`` after lowercasing.
    """
    root = (auth_dir or default_auth_dir()).resolve()
    accounts: list[SidecarAuthQuota] = []
    for entry in raw:
        if not is_json_mapping(entry):
            continue
        if not _matches_provider(entry, provider):
            continue
        accounts.append(_parse_one(entry, auth_dir=root))
    return accounts


def _matches_provider(entry: Mapping[str, JsonValue], provider: str | None) -> bool:
    if provider is None:
        return True
    wanted = provider.strip().lower()
    if wanted == "claude":
        return _is_claude_entry(entry)
    if not wanted:
        return False
    return _auth_provider(entry) == wanted


def _is_claude_entry(entry: Mapping[str, JsonValue]) -> bool:
    provider = entry.get("provider")
    if isinstance(provider, str) and provider.strip().lower() == "claude":
        return True
    entry_type = entry.get("type")
    if isinstance(entry_type, str) and entry_type.strip().lower() == "claude":
        return True
    account_type = entry.get("account_type")
    if isinstance(account_type, str) and account_type.strip().lower() == "anthropic":
        return True
    return False


def _auth_provider(entry: Mapping[str, JsonValue]) -> str | None:
    """Derive the CLIProxyAPI credential provider (e.g. ``claude``) from an auth
    file entry, or ``None`` when it cannot be identified."""
    provider = _str(entry.get("provider"))
    if provider:
        return provider.strip().lower()
    entry_type = _str(entry.get("type"))
    if entry_type:
        return entry_type.strip().lower()
    account_type = _str(entry.get("account_type"))
    if account_type and account_type.strip().lower() == "anthropic":
        return "claude"
    return None


def _parse_one(entry: Mapping[str, JsonValue], *, auth_dir: Path) -> SidecarAuthQuota:
    name = _str(entry.get("name")) or _str(entry.get("id")) or _str(entry.get("label")) or ""
    quota_field = entry.get("quota")
    quota_exceeded = False
    next_recover_at: datetime | None = None
    if is_json_mapping(quota_field):
        quota_exceeded = bool(quota_field.get("exceeded"))
        next_recover_at = _parse_datetime(quota_field.get("next_recover_at"))
    model_states_field = entry.get("model_states")
    model_states = tuple(_parse_model_states(model_states_field))
    excluded = excluded_models_for_entry(entry, auth_dir)
    return SidecarAuthQuota(
        name=name,
        auth_index=_str(entry.get("auth_index")),
        email=_str(entry.get("email")) or _str(entry.get("account")),
        provider=_auth_provider(entry),
        credential_path=_str(entry.get("path")),
        status=_str(entry.get("status")),
        status_message=_str(entry.get("status_message")),
        disabled=bool(entry.get("disabled")),
        unavailable=bool(entry.get("unavailable")),
        quota_exceeded=quota_exceeded,
        next_recover_at=next_recover_at,
        model_states=model_states,
        success=_int(entry.get("success")) or 0,
        failed=_int(entry.get("failed")) or 0,
        last_refresh=_parse_datetime(entry.get("updated_at") or entry.get("modtime") or entry.get("created_at")),
        expired=_expired_from_entry(entry, auth_dir=auth_dir),
        excluded_models=tuple(excluded) if excluded is not None else (),
        excluded_models_available=excluded is not None,
        prefix=stored_prefix_for_entry(entry, auth_dir),
        weight=_int(entry.get("weight")),
        priority=_int(entry.get("priority")),
    )


def dashboard_auth_status(auth: SidecarAuthQuota, *, now: datetime | None = None) -> str | None:
    """Map CLIProxyAPI auth-death onto the dashboard `reauth_required` badge."""
    if _looks_like_reauth(auth, now=now):
        return "reauth_required"
    return auth.status


def dashboard_status_for_auth(
    auth: SidecarAuthQuota,
    holds: Iterable[SidecarRateLimitHold] = (),
    *,
    now: datetime | None = None,
) -> str | None:
    """Report an owned exhausted-window hold as `rate_limited`.

    Re-auth still wins. A released hold does not force the badge, so an
    operator pause keeps the auth's own status.
    """
    status = dashboard_auth_status(auth, now=now)
    if status == "reauth_required":
        return status
    provider = credential_provider(auth.provider)
    if any(
        hold.name == auth.name and not hold.released and credential_provider(hold.provider) == provider
        for hold in holds
    ):
        return "rate_limited"
    return status


# Substring-matched auth-death signals. These phrases are specific enough that a
# containing message still describes a dead credential.
_AUTH_DEATH_SUBSTRINGS = (
    "authentication_error",
    "re-authenticate",
    "invalid_grant",
    "refresh token expired",
)

# Exact-matched auth-death signals. CLIProxyAPI writes `status_message` verbatim
# as "unauthorized" when a refresh returns 401 (conductor_refresh.go). Its generic
# failure branch instead leaves the raw upstream error text, which can merely
# contain the word, so this must not be matched as a substring: doing so would
# badge transient failures and reopen the hole closed in "harden Claude reauth
# status mapping".
_AUTH_DEATH_EXACT = ("unauthorized",)


def _has_auth_death_message(message: str) -> bool:
    if message in _AUTH_DEATH_EXACT:
        return True
    if any(needle in message for needle in _AUTH_DEATH_SUBSTRINGS):
        return True
    return ("oauth" in message or "access token" in message) and "expired" in message


def _looks_like_reauth(auth: SidecarAuthQuota, *, now: datetime | None = None) -> bool:
    """Report whether this credential needs an operator re-login.

    Only explicit upstream auth-failure evidence counts. A lapsed access-token
    `expired` is deliberately NOT a signal: CLIProxyAPI renews tokens from a
    background loop and exposes no field distinguishing a dead refresh token from
    a pending refresh, an unflushed write, a stopped sidecar or clock skew. No
    lapse duration turns that ambiguity into evidence, so expiry age is not
    consulted at all.

    Known limitation: a refresh-only `invalid_grant` failure leaves the listing
    `active`/available with no status message until real traffic is attempted, so
    that credential reports as healthy here.
    """
    # A quota/rate-limit cooldown also sets `unavailable`, so the message decides
    # whether an unavailable auth is dead or merely cooling down.
    if auth.quota_exceeded:
        return False
    # An operator-paused account is not a login problem, whatever its token says.
    if auth.disabled:
        return False

    message = (auth.status_message or "").strip().lower()
    if _has_auth_death_message(message):
        return True
    return auth.unavailable and (auth.status or "").strip().lower() == "unauthorized"


def oauth_expired_from_auth_file(path: str, *, auth_dir: Path | None = None) -> datetime | None:
    """Return only the auth JSON `expired` timestamp. Never returns token fields."""
    root = (auth_dir or default_auth_dir()).expanduser()
    try:
        resolved = Path(path).expanduser().resolve()
        root_resolved = root.resolve()
    except OSError:
        logger.warning("could not resolve CLIProxyAPI auth-file path for expiry")
        return None
    if not resolved.is_relative_to(root_resolved):
        logger.warning("refusing to read CLIProxyAPI auth-file expiry outside the auth directory")
        return None
    if resolved.suffix.lower() != ".json" or not resolved.is_file():
        return None
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("could not read CLIProxyAPI auth-file expiry")
        return None
    if not is_json_mapping(raw):
        return None
    return _parse_datetime(raw.get("expired") or raw.get("expires_at"))


def _expired_from_entry(entry: Mapping[str, JsonValue], *, auth_dir: Path) -> datetime | None:
    listed = _parse_datetime(entry.get("expired") or entry.get("expires_at") or entry.get("expire"))
    if listed is not None:
        return listed
    path = _str(entry.get("path"))
    if not path:
        return None
    return oauth_expired_from_auth_file(path, auth_dir=auth_dir)


def _parse_model_states(raw: JsonValue) -> list[SidecarModelQuota]:
    states: list[SidecarModelQuota] = []
    if is_json_mapping(raw):
        for model_id, value in raw.items():
            if not isinstance(model_id, str) or not model_id:
                continue
            if is_json_mapping(value):
                states.append(
                    SidecarModelQuota(
                        model=model_id,
                        quota_exceeded=bool(value.get("exceeded") or value.get("quota_exceeded")),
                        next_recover_at=_parse_datetime(value.get("next_recover_at")),
                    )
                )
            elif isinstance(value, bool):
                states.append(
                    SidecarModelQuota(
                        model=model_id,
                        quota_exceeded=value,
                        next_recover_at=None,
                    )
                )
    elif isinstance(raw, list):
        for value in raw:
            if not is_json_mapping(value):
                continue
            model_id = _str(value.get("model")) or _str(value.get("id"))
            if not model_id:
                continue
            states.append(
                SidecarModelQuota(
                    model=model_id,
                    quota_exceeded=bool(value.get("exceeded") or value.get("quota_exceeded")),
                    next_recover_at=_parse_datetime(value.get("next_recover_at")),
                )
            )
    return states


def _parse_datetime(value: JsonValue) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _str(value: JsonValue) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _int(value: JsonValue) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _float(value: JsonValue) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _oauth_usage_to_json(usage: SidecarOAuthUsage | None) -> dict[str, JsonValue] | None:
    if usage is None:
        return None
    return {
        "five_hour": _oauth_bucket_to_json(usage.five_hour),
        "seven_day": _oauth_bucket_to_json(usage.seven_day),
    }


def _oauth_bucket_to_json(bucket: SidecarOAuthUsageBucket | None) -> dict[str, JsonValue] | None:
    if bucket is None:
        return None
    return {
        "remaining_percent": bucket.remaining_percent,
        "resets_at": bucket.resets_at.isoformat() if bucket.resets_at else None,
    }


def _oauth_usage_from_json(raw: JsonValue) -> SidecarOAuthUsage | None:
    if not is_json_mapping(raw):
        return None
    return SidecarOAuthUsage(
        five_hour=_oauth_bucket_from_json(raw.get("five_hour")),
        seven_day=_oauth_bucket_from_json(raw.get("seven_day")),
    )


def _oauth_bucket_from_json(raw: JsonValue) -> SidecarOAuthUsageBucket | None:
    if not is_json_mapping(raw):
        return None
    remaining_percent = _float(raw.get("remaining_percent"))
    resets_at = _parse_datetime(raw.get("resets_at"))
    if remaining_percent is None and resets_at is None:
        return None
    return SidecarOAuthUsageBucket(
        remaining_percent=remaining_percent,
        resets_at=resets_at,
    )


def snapshot_to_json(snapshot: SidecarQuotaSnapshot) -> str:
    payload: dict[str, JsonValue] = {
        "checked_at": snapshot.checked_at.isoformat(),
        "status": snapshot.status,
        "message": snapshot.message,
        "accounts": [
            {
                "name": account.name,
                "auth_index": account.auth_index,
                "email": account.email,
                "provider": account.provider,
                "credential_path": account.credential_path,
                "status": account.status,
                "status_message": account.status_message,
                "disabled": account.disabled,
                "unavailable": account.unavailable,
                "quota_exceeded": account.quota_exceeded,
                "next_recover_at": account.next_recover_at.isoformat() if account.next_recover_at else None,
                "model_states": [
                    {
                        "model": state.model,
                        "quota_exceeded": state.quota_exceeded,
                        "next_recover_at": (state.next_recover_at.isoformat() if state.next_recover_at else None),
                    }
                    for state in account.model_states
                ],
                "success": account.success,
                "failed": account.failed,
                "last_refresh": account.last_refresh.isoformat() if account.last_refresh else None,
                "expired": account.expired.isoformat() if account.expired else None,
                "oauth_usage": _oauth_usage_to_json(account.oauth_usage),
                "excluded_models": list(account.excluded_models),
                "excluded_models_available": account.excluded_models_available,
                "prefix": account.prefix,
                "weight": account.weight,
                "priority": account.priority,
                **_grok_credits_json_fields(account.grok_credits),
            }
            for account in snapshot.accounts
        ],
        "rate_limit_holds": [_hold_to_json(hold) for hold in snapshot.rate_limit_holds],
    }
    return json.dumps(payload, separators=(",", ":"))


def snapshot_from_json(raw: str | None) -> SidecarQuotaSnapshot | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("failed to decode Claude sidecar quota snapshot")
        return None
    if not is_json_mapping(parsed):
        return None
    checked_at = _parse_datetime(parsed.get("checked_at"))
    if checked_at is None:
        return None
    status = parsed.get("status")
    if not isinstance(status, str) or status not in {"healthy", "unauthorized", "unreachable", "error", "unknown"}:
        return None
    raw_accounts = parsed.get("accounts")
    accounts: list[SidecarAuthQuota] = []
    if isinstance(raw_accounts, list):
        for entry in raw_accounts:
            if not is_json_mapping(entry):
                continue
            model_states_raw = entry.get("model_states")
            model_states: list[SidecarModelQuota] = []
            if isinstance(model_states_raw, list):
                for state in model_states_raw:
                    if not is_json_mapping(state):
                        continue
                    model = _str(state.get("model"))
                    if not model:
                        continue
                    model_states.append(
                        SidecarModelQuota(
                            model=model,
                            quota_exceeded=bool(state.get("quota_exceeded")),
                            next_recover_at=_parse_datetime(state.get("next_recover_at")),
                        )
                    )
            accounts.append(
                SidecarAuthQuota(
                    name=_str(entry.get("name")) or "",
                    auth_index=_str(entry.get("auth_index")),
                    email=_str(entry.get("email")),
                    provider=_str(entry.get("provider")),
                    credential_path=_str(entry.get("credential_path")),
                    status=_str(entry.get("status")),
                    status_message=_str(entry.get("status_message")),
                    disabled=bool(entry.get("disabled")),
                    unavailable=bool(entry.get("unavailable")),
                    quota_exceeded=bool(entry.get("quota_exceeded")),
                    next_recover_at=_parse_datetime(entry.get("next_recover_at")),
                    model_states=tuple(model_states),
                    success=_int(entry.get("success")) or 0,
                    failed=_int(entry.get("failed")) or 0,
                    last_refresh=_parse_datetime(entry.get("last_refresh")),
                    expired=_parse_datetime(entry.get("expired")),
                    oauth_usage=_oauth_usage_from_json(entry.get("oauth_usage")),
                    # An unread list is not an empty one: snapshots persisted
                    # before this key existed must decode as unreadable so the
                    # editor stays locked instead of offering an empty list a
                    # save would write over the real exclusions.
                    excluded_models=tuple(normalize_excluded_models(entry.get("excluded_models"))),
                    excluded_models_available=bool(entry.get("excluded_models_available", False)),
                    prefix=_str(entry.get("prefix")),
                    grok_credits=_grok_credits_from_json(entry.get("grok_credits")),
                    weight=_int(entry.get("weight")),
                    priority=_int(entry.get("priority")),
                )
            )
    message_field = parsed.get("message")
    message: str | None = message_field if isinstance(message_field, str) else None
    return SidecarQuotaSnapshot(
        checked_at=checked_at,
        status=status,  # type: ignore[arg-type]
        message=message,
        accounts=tuple(accounts),
        rate_limit_holds=_rate_limit_holds_from_json(parsed.get("rate_limit_holds")),
    )


def _rate_limit_holds_from_json(raw: JsonValue) -> tuple[SidecarRateLimitHold, ...]:
    if not isinstance(raw, list):
        return ()
    holds: list[SidecarRateLimitHold] = []
    for entry in raw:
        if not is_json_mapping(entry):
            continue
        name = _str(entry.get("name"))
        until = _parse_datetime(entry.get("until"))
        if name is None or until is None:
            continue
        holds.append(
            SidecarRateLimitHold(
                name=name,
                until=until,
                released=entry.get("released") is True,
                provider=credential_provider(_str(entry.get("provider"))),
                kind=_str(entry.get("kind")),
                backoff_level=_int(entry.get("backoff_level")) or 0,
            )
        )
    return tuple(holds)


def _hold_to_json(hold: SidecarRateLimitHold) -> dict[str, JsonValue]:
    """Persist a hold. Claude rows stay in the historical three-key shape."""

    payload: dict[str, JsonValue] = {
        "name": hold.name,
        "until": hold.until.isoformat(),
        "released": hold.released,
    }
    if credential_provider(hold.provider) != "claude":
        payload["provider"] = credential_provider(hold.provider)
    if hold.kind is not None:
        payload["kind"] = hold.kind
    if hold.backoff_level != 0:
        payload["backoff_level"] = hold.backoff_level
    return payload


def _grok_credits_json_fields(credits: GrokCreditsQuota | None) -> dict[str, JsonValue]:
    encoded = _grok_credits_to_json(credits)
    if encoded is None:
        return {}
    return {"grok_credits": encoded}


def _grok_credits_to_json(credits: GrokCreditsQuota | None) -> dict[str, JsonValue] | None:
    if credits is None:
        return None
    if (
        not credits.windows
        and credits.prepaid_credits is None
        and credits.token_rollup is None
        and credits.refreshed_at is None
    ):
        return None
    return {
        "windows": [_grok_window_to_json(window) for window in credits.windows],
        "prepaid_credits": credits.prepaid_credits,
        "refreshed_at": credits.refreshed_at.isoformat() if credits.refreshed_at else None,
        "token_rollup": _grok_rollup_to_json(credits.token_rollup),
    }


def _grok_window_to_json(window: GrokCreditWindow) -> dict[str, JsonValue]:
    return {
        "id": window.id,
        "label": window.label,
        "kind": window.kind,
        "percent_used": window.percent_used,
        "percent_remaining": window.percent_remaining,
        "starts_at": window.starts_at.isoformat() if window.starts_at else None,
        "resets_at": window.resets_at.isoformat() if window.resets_at else None,
    }


def _grok_rollup_to_json(rollup: GrokTokenRollup | None) -> dict[str, JsonValue] | None:
    if rollup is None:
        return None
    return {
        "input_tokens": rollup.input_tokens,
        "output_tokens": rollup.output_tokens,
        "reasoning_tokens": rollup.reasoning_tokens,
        "cached_tokens": rollup.cached_tokens,
        "total_tokens": rollup.total_tokens,
        "request_count": rollup.request_count,
        "window_start": rollup.window_start.isoformat() if rollup.window_start else None,
    }


def _grok_credits_from_json(raw: JsonValue) -> GrokCreditsQuota | None:
    if not is_json_mapping(raw):
        return None
    windows_raw = raw.get("windows")
    windows: list[GrokCreditWindow] = []
    if isinstance(windows_raw, list):
        for entry in windows_raw:
            window = _grok_window_from_json(entry)
            if window is not None:
                windows.append(window)
    prepaid = _int(raw.get("prepaid_credits"))
    rollup = _grok_rollup_from_json(raw.get("token_rollup"))
    refreshed_at = _parse_datetime(raw.get("refreshed_at"))
    if not windows and prepaid is None and rollup is None and refreshed_at is None:
        return None
    return GrokCreditsQuota(
        windows=tuple(windows),
        prepaid_credits=prepaid,
        refreshed_at=refreshed_at,
        token_rollup=rollup,
    )


def _grok_window_from_json(raw: JsonValue) -> GrokCreditWindow | None:
    if not is_json_mapping(raw):
        return None
    window_id = _str(raw.get("id"))
    label = _str(raw.get("label"))
    kind = _str(raw.get("kind"))
    percent_used = _float(raw.get("percent_used"))
    percent_remaining = _float(raw.get("percent_remaining"))
    if window_id is None or label is None or kind is None or percent_used is None or percent_remaining is None:
        return None
    return GrokCreditWindow(
        id=window_id,
        label=label,
        kind=kind,
        percent_used=percent_used,
        percent_remaining=percent_remaining,
        starts_at=_parse_datetime(raw.get("starts_at")),
        resets_at=_parse_datetime(raw.get("resets_at")),
    )


def _grok_rollup_from_json(raw: JsonValue) -> GrokTokenRollup | None:
    if not is_json_mapping(raw):
        return None
    return GrokTokenRollup(
        input_tokens=_int(raw.get("input_tokens")) or 0,
        output_tokens=_int(raw.get("output_tokens")) or 0,
        reasoning_tokens=_int(raw.get("reasoning_tokens")) or 0,
        cached_tokens=_int(raw.get("cached_tokens")) or 0,
        total_tokens=_int(raw.get("total_tokens")) or 0,
        request_count=_int(raw.get("request_count")) or 0,
        window_start=_parse_datetime(raw.get("window_start")),
    )
