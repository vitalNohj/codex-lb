from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

from app.core.clients.http import lease_http_session
from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping
from app.modules.claude_sidecar.quota import (
    SidecarOAuthUsage,
    SidecarOAuthUsageBucket,
)

CLAUDE_OAUTH_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_OAUTH_USAGE_BETA = "oauth-2025-04-20"


class ClaudeOAuthUsageError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ClaudeOAuthCredential:
    access_token: str


async def load_claude_oauth_credential(path: str | None) -> ClaudeOAuthCredential | None:
    if not path:
        return None
    return await asyncio.to_thread(_load_claude_oauth_credential_sync, path)


def _load_claude_oauth_credential_sync(path: str) -> ClaudeOAuthCredential | None:
    try:
        text = Path(path).expanduser().read_text(encoding="utf-8")
        parsed = json.loads(text)
    except (OSError, json.JSONDecodeError):
        return None
    if not is_json_mapping(parsed):
        return None
    access_token = parsed.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        return None
    return ClaudeOAuthCredential(access_token=access_token.strip())


async def fetch_claude_oauth_usage(credential: ClaudeOAuthCredential) -> SidecarOAuthUsage:
    headers = {
        "Authorization": f"Bearer {credential.access_token}",
        "anthropic-beta": CLAUDE_OAUTH_USAGE_BETA,
    }
    timeout = aiohttp.ClientTimeout(total=10.0)
    async with lease_http_session() as http:
        try:
            async with http.session.get(CLAUDE_OAUTH_USAGE_URL, headers=headers, timeout=timeout) as response:
                status = response.status
                data = await response.json(content_type=None) if status < 400 else None
        except (aiohttp.ClientError, ValueError) as exc:
            raise ClaudeOAuthUsageError("failed to fetch Claude OAuth usage") from exc
    if status >= 400:
        raise ClaudeOAuthUsageError(f"Claude OAuth usage returned HTTP {status}")
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
