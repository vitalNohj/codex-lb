from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping

logger = logging.getLogger(__name__)

SidecarQuotaStatus = Literal["healthy", "unauthorized", "unreachable", "error", "unknown"]


@dataclass(frozen=True, slots=True)
class SidecarModelQuota:
    model: str
    quota_exceeded: bool
    next_recover_at: datetime | None


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


@dataclass(frozen=True, slots=True)
class SidecarQuotaSnapshot:
    checked_at: datetime
    status: SidecarQuotaStatus
    message: str | None
    accounts: tuple[SidecarAuthQuota, ...] = field(default_factory=tuple)


def parse_auth_files(raw: Iterable[Mapping[str, JsonValue]]) -> list[SidecarAuthQuota]:
    accounts: list[SidecarAuthQuota] = []
    for entry in raw:
        if not is_json_mapping(entry):
            continue
        if not _is_claude_entry(entry):
            continue
        accounts.append(_parse_one(entry))
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


def _parse_one(entry: Mapping[str, JsonValue]) -> SidecarAuthQuota:
    name = _str(entry.get("name")) or _str(entry.get("id")) or _str(entry.get("label")) or ""
    quota_field = entry.get("quota")
    quota_exceeded = False
    next_recover_at: datetime | None = None
    if is_json_mapping(quota_field):
        quota_exceeded = bool(quota_field.get("exceeded"))
        next_recover_at = _parse_datetime(quota_field.get("next_recover_at"))
    model_states_field = entry.get("model_states")
    model_states = tuple(_parse_model_states(model_states_field))
    return SidecarAuthQuota(
        name=name,
        auth_index=_str(entry.get("auth_index")),
        email=_str(entry.get("email")) or _str(entry.get("account")),
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
    )


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
                        "next_recover_at": (
                            state.next_recover_at.isoformat() if state.next_recover_at else None
                        ),
                    }
                    for state in account.model_states
                ],
                "success": account.success,
                "failed": account.failed,
                "last_refresh": account.last_refresh.isoformat() if account.last_refresh else None,
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
