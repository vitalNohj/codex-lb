from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.modules.claude_sidecar.quota import (
    SidecarAuthQuota,
    SidecarModelQuota,
    SidecarQuotaSnapshot,
    dashboard_auth_status,
    oauth_expired_from_auth_file,
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
        state.model == "claude-sonnet-4-5-20250929" and state.quota_exceeded for state in decoded_only.model_states
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
                "excluded_models": ["claude-demo-*"],
            }
        ]
    )

    assert accounts[0].excluded_models == ("claude-demo-*",)
    assert accounts[0].excluded_models_available is True


def test_parse_auth_files_marks_denormalized_entry_list_unavailable():
    # A list a save would rewrite is not the file's true content, so it must not
    # be offered as an editable list a whole-list PUT would truncate on disk.
    accounts = parse_auth_files(
        [
            {
                "name": "claude-a.json",
                "provider": "claude",
                "excluded_models": ["  claude-demo-* ", "CLAUDE-DEMO-*"],
            }
        ]
    )

    assert accounts[0].excluded_models == ()
    assert accounts[0].excluded_models_available is False


def test_parse_auth_files_marks_unreadable_excluded_models_unavailable(tmp_path):
    accounts = parse_auth_files(
        [
            {
                "name": "claude-a.json",
                "provider": "claude",
                "path": str(tmp_path / "missing.json"),
            }
        ],
        auth_dir=tmp_path,
    )

    assert accounts[0].excluded_models == ()
    assert accounts[0].excluded_models_available is False


def test_parse_auth_files_reads_excluded_models_from_auth_file(tmp_path):
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
        ],
        auth_dir=tmp_path,
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
                excluded_models_available=True,
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
    # A snapshot persisted before this key existed recorded no read at all, so
    # it must decode as unreadable rather than as an empty, saveable list.
    assert decoded.accounts[0].excluded_models_available is False


def _auth(**overrides) -> SidecarAuthQuota:
    fields: dict = {
        "name": "claude-a.json",
        "auth_index": "abc",
        "email": "a@example.com",
        "status": "active",
        "status_message": None,
        "disabled": False,
        "unavailable": False,
        "quota_exceeded": False,
        "next_recover_at": None,
        "model_states": (),
        "success": 0,
        "failed": 0,
        "last_refresh": None,
        "expired": None,
    }
    fields.update(overrides)
    return SidecarAuthQuota(**fields)


def test_parse_auth_files_reads_listed_expired():
    accounts = parse_auth_files(
        [
            {
                "name": "claude-a.json",
                "provider": "claude",
                "email": "a@example.com",
                "status": "active",
                "expired": "2026-09-07T14:05:05Z",
            }
        ]
    )

    assert accounts[0].expired == datetime(2026, 9, 7, 14, 5, 5, tzinfo=timezone.utc)


def test_parse_auth_files_reads_expired_from_disk_without_copying_tokens(tmp_path: Path) -> None:
    auth_path = tmp_path / "claude-a.json"
    auth_path.write_text(
        json.dumps(
            {
                "expired": "2026-09-07T14:05:05Z",
                "access_token": "synthetic-access-token",
                "refresh_token": "synthetic-refresh-token",
                "email": "a@example.com",
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
                "status": "active",
                "path": str(auth_path),
            }
        ],
        auth_dir=tmp_path,
    )

    assert accounts[0].expired == datetime(2026, 9, 7, 14, 5, 5, tzinfo=timezone.utc)
    snapshot = SidecarQuotaSnapshot(
        checked_at=datetime(2026, 9, 8, 21, 0, tzinfo=timezone.utc),
        status="healthy",
        message=None,
        accounts=tuple(accounts),
    )
    raw = snapshot_to_json(snapshot)
    assert "synthetic-access-token" not in raw
    assert "synthetic-refresh-token" not in raw
    assert "access_token" not in raw
    assert "refresh_token" not in raw


def test_oauth_expired_from_auth_file_refuses_path_outside_auth_dir(tmp_path: Path) -> None:
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"expired": "2020-01-01T00:00:00Z"}), encoding="utf-8")

    assert oauth_expired_from_auth_file(str(outside), auth_dir=auth_dir) is None


def test_listed_expired_wins_over_disk_file(tmp_path: Path) -> None:
    auth_path = tmp_path / "claude-a.json"
    auth_path.write_text(
        json.dumps({"expired": "2020-01-01T00:00:00Z", "access_token": "synthetic-access-token"}),
        encoding="utf-8",
    )

    accounts = parse_auth_files(
        [
            {
                "name": "claude-a.json",
                "provider": "claude",
                "path": str(auth_path),
                "expired": "2026-09-07T14:05:05Z",
            }
        ],
        auth_dir=tmp_path,
    )

    assert accounts[0].expired == datetime(2026, 9, 7, 14, 5, 5, tzinfo=timezone.utc)


# CLIProxyAPI renews Claude access tokens from a background loop and exposes no
# field distinguishing a dead refresh token from a pending refresh, an unflushed
# write, a stopped sidecar or clock skew. Access-token expiry age is therefore
# never a re-auth signal, at any lapse duration.
_NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "lapse",
    [
        timedelta(minutes=2),
        timedelta(hours=3, minutes=59),
        timedelta(hours=4, minutes=1),
        timedelta(days=1),
        timedelta(days=90),
    ],
    ids=["minutes", "just-under-4h", "just-over-4h", "one-day", "ninety-days"],
)
def test_expiry_age_alone_never_badges_regardless_of_lapse(lapse: timedelta) -> None:
    """A lapsed access-token expiry is suggestive, never evidence.

    The persisted `expired` trails the live token after a restart, a not-yet-
    flushed refresh, or clock skew, so badging on it cries wolf on healthy
    accounts. No lapse duration resolves that ambiguity, so none is used.
    """
    auth = _auth(expired=_NOW - lapse, status="active")

    assert dashboard_auth_status(auth, now=_NOW) == "active"


def test_silent_dead_refresh_reports_active_known_limitation() -> None:
    """Accepted coverage limit, asserted so it cannot change unnoticed.

    A refresh-only `invalid_grant` failure leaves the CLIProxyAPI listing
    `active`/available with an empty status message while it retries. Upstream
    publishes nothing to distinguish it until real traffic is attempted, so this
    credential reports as healthy rather than being guessed at.
    """
    auth = _auth(status="active", unavailable=False, status_message=None, expired=_NOW - timedelta(days=2))

    assert dashboard_auth_status(auth, now=_NOW) == "active"


def test_paused_account_with_lapsed_expiry_keeps_pause_label() -> None:
    auth = _auth(status="disabled", disabled=True, expired=_NOW - timedelta(days=2))

    assert dashboard_auth_status(auth, now=_NOW) == "disabled"


def test_quota_cooldown_with_lapsed_expiry_is_not_reauth() -> None:
    """A quota cooldown also sets `unavailable`; it must not read as auth death."""
    auth = _auth(
        status="rate_limited",
        status_message="Quota exceeded",
        quota_exceeded=True,
        unavailable=True,
        failed=7,
        expired=_NOW - timedelta(days=1),
    )

    assert dashboard_auth_status(auth, now=_NOW) == "rate_limited"


@pytest.mark.parametrize(
    "message",
    [
        "request failed: 502 unauthorized proxy upstream",
        "unauthorized_client detected downstream",
        "connection reset while handling unauthorized retry",
    ],
    ids=["transient-502", "different-oauth-code", "transient-reset"],
)
def test_message_merely_containing_unauthorized_is_not_reauth(message: str) -> None:
    """`unauthorized` is matched exactly, never as a substring.

    CLIProxyAPI writes `status_message` verbatim as "unauthorized" on a refresh
    401, but its generic failure branch leaves the raw upstream error text, which
    can merely contain the word. Substring matching would badge those transient
    failures and reopen the hole closed by "harden Claude reauth status mapping".
    """
    auth = _auth(status="error", status_message=message, unavailable=True, failed=1)

    assert dashboard_auth_status(auth, now=_NOW) == "error"


def test_unauthorized_status_message_is_matched_after_trimming_and_casefold() -> None:
    auth = _auth(status="error", status_message="  Unauthorized  ", unavailable=True)

    assert dashboard_auth_status(auth, now=_NOW) == "reauth_required"


def test_unauthorized_status_message_is_reauth_even_with_fresh_token() -> None:
    """Upstream sets status=error + status_message=unauthorized on refresh 401.

    It never sets `status` itself to `unauthorized`, so the message must be
    honoured or this genuine re-auth need would be lost.
    """
    auth = _auth(
        status="error",
        status_message="unauthorized",
        unavailable=True,
        failed=3,
        expired=_NOW + timedelta(hours=2),
    )

    assert dashboard_auth_status(auth, now=_NOW) == "reauth_required"


def test_invalid_grant_status_message_is_reauth_before_expiry_lapses() -> None:
    auth = _auth(
        status="error",
        status_message="invalid_grant",
        unavailable=True,
        expired=_NOW + timedelta(hours=2),
    )

    assert dashboard_auth_status(auth, now=_NOW) == "reauth_required"


def test_dashboard_auth_status_future_expiry_keeps_active() -> None:
    auth = _auth(expired=datetime(2026, 9, 9, 5, 29, 23, tzinfo=timezone.utc), status="active")
    now = datetime(2026, 9, 8, 21, 30, tzinfo=timezone.utc)

    assert dashboard_auth_status(auth, now=now) == "active"


def test_dashboard_auth_status_missing_expiry_keeps_active() -> None:
    assert dashboard_auth_status(_auth(expired=None, status="active")) == "active"


def test_dashboard_auth_status_quota_exceeded_with_future_expiry_is_not_reauth() -> None:
    auth = _auth(
        status="rate_limited",
        status_message="Quota exceeded",
        quota_exceeded=True,
        expired=datetime(2026, 9, 9, 5, 29, 23, tzinfo=timezone.utc),
    )
    now = datetime(2026, 9, 8, 21, 30, tzinfo=timezone.utc)

    assert dashboard_auth_status(auth, now=now) == "rate_limited"


def test_snapshot_round_trips_expired() -> None:
    snapshot = SidecarQuotaSnapshot(
        checked_at=datetime(2026, 9, 8, 21, 0, tzinfo=timezone.utc),
        status="healthy",
        message=None,
        accounts=(_auth(expired=datetime(2026, 9, 7, 14, 5, 5, tzinfo=timezone.utc)),),
    )

    decoded = snapshot_from_json(snapshot_to_json(snapshot))

    assert decoded is not None
    assert decoded.accounts[0].expired == datetime(2026, 9, 7, 14, 5, 5, tzinfo=timezone.utc)
