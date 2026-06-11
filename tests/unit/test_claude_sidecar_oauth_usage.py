from __future__ import annotations

import json

import pytest

from app.modules.claude_sidecar.oauth_usage import (
    load_claude_oauth_credential,
    parse_claude_oauth_usage,
)

pytestmark = pytest.mark.unit


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
async def test_load_claude_oauth_credential_reads_cli_proxy_api_token(tmp_path) -> None:
    auth_file = tmp_path / "claude-user@example.com.json"
    auth_file.write_text(
        json.dumps(
            {
                "access_token": "sk-ant-oat01-token",
                "refresh_token": "sk-ant-ort01-token",
                "email": "user@example.com",
                "type": "claude",
            }
        ),
        encoding="utf-8",
    )

    credential = await load_claude_oauth_credential(str(auth_file))

    assert credential is not None
    assert credential.access_token == "sk-ant-oat01-token"


@pytest.mark.asyncio
async def test_load_claude_oauth_credential_ignores_missing_token(tmp_path) -> None:
    auth_file = tmp_path / "claude-user@example.com.json"
    auth_file.write_text(json.dumps({"email": "user@example.com", "type": "claude"}), encoding="utf-8")

    assert await load_claude_oauth_credential(str(auth_file)) is None
