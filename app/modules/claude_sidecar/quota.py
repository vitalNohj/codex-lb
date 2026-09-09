from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping
from app.modules.claude_sidecar.excluded_models import (
    default_auth_dir,
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


@dataclass(frozen=True, slots=True)
class SidecarQuotaSnapshot:
    checked_at: datetime
    status: SidecarQuotaStatus
    message: str | None
    accounts: tuple[SidecarAuthQuota, ...] = field(default_factory=tuple)


def parse_auth_files(
    raw: Iterable[Mapping[str, JsonValue]],
    *,
    auth_dir: Path | None = None,
) -> list[SidecarAuthQuota]:
    root = (auth_dir or default_auth_dir()).resolve()
    accounts: list[SidecarAuthQuota] = []
    for entry in raw:
        if not is_json_mapping(entry):
            continue
        if not _is_claude_entry(entry):
            continue
        accounts.append(_parse_one(entry, auth_dir=root))
    return accounts


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
    )


def dashboard_auth_status(auth: SidecarAuthQuota, *, now: datetime | None = None) -> str | None:
    """Map CLIProxyAPI auth-death onto the dashboard `reauth_required` badge."""
    if _looks_like_reauth(auth, now=now):
        return "reauth_required"
    return auth.status


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
            }
            for account in snapshot.accounts
        ],
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
                )
            )
    message_field = parsed.get("message")
    message: str | None = message_field if isinstance(message_field, str) else None
    return SidecarQuotaSnapshot(
        checked_at=checked_at,
        status=status,  # type: ignore[arg-type]
        message=message,
        accounts=tuple(accounts),
    )
