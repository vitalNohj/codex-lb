from __future__ import annotations

from collections.abc import Mapping

import pytest

from app.core.clients.claude_sidecar import ClaudeSidecarError, ClaudeSidecarUnavailableError
from app.core.types import JsonValue
from app.modules.claude_sidecar.oauth_usage import (
    ClaudeOAuthUsageError,
    fetch_claude_oauth_usage,
    parse_claude_oauth_usage,
)

pytestmark = pytest.mark.unit


class _FakeClient:
    def __init__(self, *, result: JsonValue | Exception) -> None:
        self._result = result
        self.last_auth_index: str | None = None
        self.last_method: str | None = None
        self.last_url: str | None = None
        self.last_header: Mapping[str, str] | None = None

    async def api_call(
        self,
        *,
        auth_index: str,
        method: str,
        url: str,
        header: Mapping[str, str],
    ) -> JsonValue:
        self.last_auth_index = auth_index
        self.last_method = method
        self.last_url = url
        self.last_header = header
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def test_parse_claude_oauth_usage_converts_utilization_to_remaining_percent() -> None:
    usage = parse_claude_oauth_usage(
        {
            "five_hour": {
                "utilization": 0.42,
                "resets_at": "2026-05-05T17:00:00Z",
            },
            "seven_day": {
                "utilization": 61.0,
                "resets_at": "2026-05-12T12:00:00+00:00",
            },
        }
    )

    assert usage.five_hour is not None
    assert usage.five_hour.remaining_percent == 58.0
    assert usage.five_hour.resets_at is not None
    assert usage.seven_day is not None
    assert usage.seven_day.remaining_percent == 39.0


@pytest.mark.asyncio
async def test_fetch_claude_oauth_usage_routes_through_api_call() -> None:
    client = _FakeClient(
        result={
            "five_hour": {"utilization": 0.25, "resets_at": "2026-05-05T17:00:00Z"},
            "seven_day": {"utilization": 0.5, "resets_at": "2026-05-12T12:00:00Z"},
        }
    )

    usage = await fetch_claude_oauth_usage(client, "0")

    assert client.last_auth_index == "0"
    assert client.last_method == "GET"
    assert client.last_url == "https://api.anthropic.com/api/oauth/usage"
    assert client.last_header is not None
    assert client.last_header["Authorization"] == "Bearer $TOKEN$"
    assert client.last_header["anthropic-beta"] == "oauth-2025-04-20"
    assert usage.five_hour is not None
    assert usage.five_hour.remaining_percent == 75.0


@pytest.mark.asyncio
async def test_fetch_claude_oauth_usage_wraps_upstream_error() -> None:
    client = _FakeClient(result=ClaudeSidecarError(429, "rate limited"))

    with pytest.raises(ClaudeOAuthUsageError):
        await fetch_claude_oauth_usage(client, "0")


@pytest.mark.asyncio
async def test_fetch_claude_oauth_usage_wraps_unavailable_error() -> None:
    client = _FakeClient(result=ClaudeSidecarUnavailableError("down"))

    with pytest.raises(ClaudeOAuthUsageError):
        await fetch_claude_oauth_usage(client, "0")


@pytest.mark.asyncio
async def test_fetch_claude_oauth_usage_rejects_non_object_body() -> None:
    client = _FakeClient(result=[1, 2, 3])

    with pytest.raises(ClaudeOAuthUsageError):
        await fetch_claude_oauth_usage(client, "0")
