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
    assert only.email == "account1@example.com"
    assert only.provider == "claude"
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
    assert decoded_only.provider == accounts[0].provider
    assert decoded_only.quota_exceeded is True
    assert decoded_only.next_recover_at == datetime(2026, 6, 10, 23, 30, tzinfo=timezone.utc)
    assert any(
        state.model == "claude-sonnet-4-5-20250929" and state.quota_exceeded
        for state in decoded_only.model_states
    )
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


def test_parse_auth_files_reads_excluded_models_from_entry():
    accounts = parse_auth_files(
        [
            {
                "name": "claude-a.json",
                "provider": "claude",
                "email": "a@example.com",
                "excluded_models": ["  claude-demo-* ", "CLAUDE-DEMO-*"],
            }
        ]
    )

    assert accounts[0].excluded_models == ("claude-demo-*",)
    assert accounts[0].excluded_models_available is True


def test_parse_auth_files_marks_unreadable_excluded_models_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.modules.claude_sidecar.excluded_models.default_auth_dir",
        lambda: tmp_path,
    )

    accounts = parse_auth_files(
        [
            {
                "name": "claude-a.json",
                "provider": "claude",
                "path": str(tmp_path / "missing.json"),
            }
        ]
    )

    assert accounts[0].excluded_models == ()
    assert accounts[0].excluded_models_available is False


def test_parse_auth_files_reads_excluded_models_from_auth_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.modules.claude_sidecar.excluded_models.default_auth_dir",
        lambda: tmp_path,
    )
    auth_path = tmp_path / "claude-a.json"
    auth_path.write_text(
        json.dumps(
            {
                "access_token": "synthetic-access-token",
                "excluded_models": ["claude-demo-*"],
            }
        ),
        encoding="utf-8",
    )

    accounts = parse_auth_files(
        [
            {
                "name": "claude-a.json",
                "provider": "claude",
                "email": "a@example.com",
                "path": str(auth_path),
            }
        ]
    )

    assert accounts[0].excluded_models == ("claude-demo-*",)


def test_snapshot_round_trips_excluded_models():
    snapshot = SidecarQuotaSnapshot(
        checked_at=datetime(2026, 6, 10, 22, 30, tzinfo=timezone.utc),
        status="healthy",
        message=None,
        accounts=(
            SidecarAuthQuota(
                name="claude-a.json",
                auth_index="0",
                email="a@example.com",
                status="active",
                status_message=None,
                disabled=False,
                unavailable=False,
                quota_exceeded=False,
                next_recover_at=None,
                model_states=(),
                success=0,
                failed=0,
                last_refresh=None,
                excluded_models=("claude-demo-*",),
            ),
        ),
    )

    decoded = snapshot_from_json(snapshot_to_json(snapshot))

    assert decoded is not None
    assert decoded.accounts[0].excluded_models == ("claude-demo-*",)
    assert decoded.accounts[0].excluded_models_available is True


def test_snapshot_round_trips_unavailable_excluded_models():
    snapshot = SidecarQuotaSnapshot(
        checked_at=datetime(2026, 6, 10, 22, 30, tzinfo=timezone.utc),
        status="healthy",
        message=None,
        accounts=(
            SidecarAuthQuota(
                name="claude-a.json",
                auth_index="0",
                email="a@example.com",
                status="active",
                status_message=None,
                disabled=False,
                unavailable=False,
                quota_exceeded=False,
                next_recover_at=None,
                model_states=(),
                success=0,
                failed=0,
                last_refresh=None,
                excluded_models=(),
                excluded_models_available=False,
            ),
        ),
    )

    decoded = snapshot_from_json(snapshot_to_json(snapshot))

    assert decoded is not None
    assert decoded.accounts[0].excluded_models_available is False


def test_snapshot_without_excluded_models_key_decodes_to_empty_tuple():
    raw = json.dumps(
        {
            "checked_at": "2026-06-10T22:30:00+00:00",
            "status": "healthy",
            "message": None,
            "accounts": [{"name": "claude-a.json"}],
        }
    )

    decoded = snapshot_from_json(raw)

    assert decoded is not None
    assert decoded.accounts[0].excluded_models == ()
