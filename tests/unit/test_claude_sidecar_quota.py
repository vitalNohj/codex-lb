from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.modules.claude_sidecar.quota import (
    SidecarAuthQuota,
    SidecarModelQuota,
    SidecarQuotaSnapshot,
    parse_auth_files,
    snapshot_from_json,
    snapshot_to_json,
)

_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _load(name: str) -> list[dict]:
    payload = json.loads((_FIXTURE_DIR / name).read_text())
    files = payload.get("files")
    assert isinstance(files, list)
    return files


def test_parse_live_fixture_keeps_claude_entry_without_quota_block():
    files = _load("claude_sidecar_auth_files.json")

    accounts = parse_auth_files(files)

    assert len(accounts) == 1
    only = accounts[0]
    assert isinstance(only, SidecarAuthQuota)
    assert only.email == "jvwarrior@gmail.com"
    assert only.quota_exceeded is False
    assert only.next_recover_at is None
    assert only.model_states == ()
    assert only.status == "active"
    assert only.disabled is False
    assert only.unavailable is False


def test_parse_exceeded_fixture_extracts_quota_and_model_states():
    files = _load("claude_sidecar_auth_files_exceeded.json")

    accounts = parse_auth_files(files)

    assert len(accounts) == 1, "non-claude provider entries must be filtered out"
    only = accounts[0]
    assert only.email == "exceeded@example.com"
    assert only.quota_exceeded is True
    assert only.next_recover_at == datetime(2026, 6, 10, 23, 30, tzinfo=timezone.utc)
    assert only.status == "rate_limited"
    assert only.status_message == "Quota exceeded"
    assert only.success == 12
    assert only.failed == 3
    assert len(only.model_states) == 2
    by_model = {state.model: state for state in only.model_states}
    assert by_model["claude-sonnet-4-5-20250929"].quota_exceeded is True
    assert by_model["claude-opus-4-1"].quota_exceeded is False


def test_snapshot_round_trips_through_json():
    files = _load("claude_sidecar_auth_files_exceeded.json")
    accounts = parse_auth_files(files)
    snapshot = SidecarQuotaSnapshot(
        checked_at=datetime(2026, 6, 10, 22, 30, tzinfo=timezone.utc),
        status="healthy",
        message=None,
        accounts=tuple(accounts),
    )

    raw = snapshot_to_json(snapshot)
    decoded = snapshot_from_json(raw)

    assert decoded is not None
    assert decoded.status == "healthy"
    assert decoded.checked_at == snapshot.checked_at
    assert len(decoded.accounts) == 1
    decoded_only = decoded.accounts[0]
    assert decoded_only.email == "exceeded@example.com"
    assert decoded_only.quota_exceeded is True
    assert decoded_only.next_recover_at == datetime(2026, 6, 10, 23, 30, tzinfo=timezone.utc)
    assert any(state.model == "claude-sonnet-4-5-20250929" and state.quota_exceeded for state in decoded_only.model_states)
    assert isinstance(decoded_only.model_states[0], SidecarModelQuota)


def test_snapshot_from_json_handles_unauthorized_status():
    snapshot = SidecarQuotaSnapshot(
        checked_at=datetime(2026, 6, 10, 22, 30, tzinfo=timezone.utc),
        status="unauthorized",
        message="HTTP 401",
        accounts=(),
    )
    raw = snapshot_to_json(snapshot)
    decoded = snapshot_from_json(raw)

    assert decoded is not None
    assert decoded.status == "unauthorized"
    assert decoded.message == "HTTP 401"
    assert decoded.accounts == ()


def test_snapshot_from_json_returns_none_for_garbage():
    assert snapshot_from_json(None) is None
    assert snapshot_from_json("not json") is None
    assert snapshot_from_json("{}") is None
