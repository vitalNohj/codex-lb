from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.core.clients.claude_sidecar import ClaudeSidecarError
from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping
from app.modules.claude_sidecar.quota import (
    SidecarOAuthUsage,
    SidecarOAuthUsageBucket,
)

if TYPE_CHECKING:
    from app.core.clients.claude_sidecar import ClaudeSidecarClient

CLAUDE_OAUTH_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_OAUTH_USAGE_BETA = "oauth-2025-04-20"


class ClaudeOAuthUsageError(Exception):
    pass


async def fetch_claude_oauth_usage(client: ClaudeSidecarClient, auth_index: str) -> SidecarOAuthUsage:
    """Fetch Anthropic OAuth usage for an auth through CLIProxyAPI.

    The request is issued via CLIProxyAPI's ``/v0/management/api-call`` passthrough
    so the upstream call uses the account's stored token (``$TOKEN$`` substitution)
    and its configured ``proxy-url``. codex-lb never reads credential files nor
    contacts ``api.anthropic.com`` directly.
    """
    try:
        data = await client.api_call(
            auth_index=auth_index,
            method="GET",
            url=CLAUDE_OAUTH_USAGE_URL,
            header={
                "Authorization": "Bearer $TOKEN$",
                "anthropic-beta": CLAUDE_OAUTH_USAGE_BETA,
            },
        )
    except ClaudeSidecarError as exc:
        raise ClaudeOAuthUsageError("failed to fetch Claude OAuth usage") from exc
    if not is_json_mapping(data):
        raise ClaudeOAuthUsageError("Claude OAuth usage response was not a JSON object")
    return parse_claude_oauth_usage(data)


def parse_claude_oauth_usage(payload: Mapping[str, JsonValue]) -> SidecarOAuthUsage:
    return SidecarOAuthUsage(
        five_hour=_parse_bucket(payload.get("five_hour")),
        seven_day=_parse_bucket(payload.get("seven_day")),
    )


def _parse_bucket(raw: JsonValue) -> SidecarOAuthUsageBucket | None:
    if not is_json_mapping(raw):
        return None
    utilization = _float(raw.get("utilization"))
    resets_at = _parse_datetime(raw.get("resets_at"))
    remaining_percent = None if utilization is None else max(0.0, 100.0 - _utilization_percent(utilization))
    if remaining_percent is None and resets_at is None:
        return None
    return SidecarOAuthUsageBucket(
        remaining_percent=remaining_percent,
        resets_at=resets_at,
    )


def _utilization_percent(value: float) -> float:
    return value * 100.0 if 0.0 <= value <= 1.0 else value


def _float(value: JsonValue) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


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
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
