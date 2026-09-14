"""Parser tests for the OpenCode Go ``/usage`` payload.

Fixtures are explicit and local - no network, no credentials, no production
data. The canonical fixture mirrors the response shape evidenced by two
independent MIT implementations (see ``app/core/usage/opencode_go_quota``); the
rest deliberately probe what happens when upstream deviates from it, because the
endpoint is undocumented and may change without notice.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.usage.opencode_go_quota import (
    OpenCodeGoQuotaParseError,
    parse_opencode_go_usage,
)

pytestmark = pytest.mark.unit


def _usage_payload(**overrides) -> dict:
    """The response shape both reviewed parsers agree on."""
    windows = {
        "rolling": {"status": "ok", "percent": 12.5, "resetsAt": "2026-09-14T17:00:00Z"},
        "weekly": {"status": "ok", "percent": 40, "resetsAt": "2026-09-20T00:00:00Z"},
        "monthly": {"status": "ok", "percent": 66.25, "resetsAt": "2026-10-01T00:00:00Z"},
    }
    windows.update(overrides)
    return {"usage": windows}


def test_parses_all_three_windows_in_dashboard_order():
    quota = parse_opencode_go_usage(_usage_payload())

    assert [window.key for window in quota.windows] == ["five_hour", "weekly", "monthly"]
    # Upstream's own key is preserved so the rolling -> five_hour mapping stays
    # auditable against a future authenticated capture.
    assert [window.upstream_key for window in quota.windows] == ["rolling", "weekly", "monthly"]
    assert [window.percent_used for window in quota.windows] == [12.5, 40.0, 66.25]
    assert quota.window("five_hour").resets_at == datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc)


def test_scope_is_unknown_and_no_per_model_breakdown_is_invented():
    """Upstream sends three unlabelled windows and no model dimension.

    Labelling that "account total" would contradict the docs (limits are defined
    per model) and labelling it per-model would invent a dimension that is not
    in the payload, so it stays unknown.
    """
    quota = parse_opencode_go_usage(_usage_payload())

    assert quota.scope == "unknown"
    assert quota.model_breakdown_available is False


def test_percent_is_read_as_used_not_remaining():
    quota = parse_opencode_go_usage(_usage_payload(rolling={"status": "ok", "percent": 90, "resetsAt": None}))

    window = quota.window("five_hour")
    assert window.percent_used == 90.0
    assert window.limit_reached is False
    # No remaining figure is derived anywhere: the used direction rests on a
    # single-source inference and must not gain a false second confirmation.
    assert not hasattr(window, "percent_remaining")


@pytest.mark.parametrize(
    ("status", "percent", "expected_status", "expected_limit_reached"),
    [
        ("ok", 0, "ok", False),
        ("ok", 99.9, "ok", False),
        ("ok", 100, "ok", True),
        ("rate-limited", 100, "rate_limited", True),
        # Exhaustion is authoritative from status alone, whatever percent says.
        ("rate-limited", 3, "rate_limited", True),
        ("RATE-LIMITED", 50, "rate_limited", True),
    ],
)
def test_limit_reached_semantics(status, percent, expected_status, expected_limit_reached):
    quota = parse_opencode_go_usage(
        _usage_payload(rolling={"status": status, "percent": percent, "resetsAt": "2026-09-14T17:00:00Z"})
    )

    window = quota.window("five_hour")
    assert window.status == expected_status
    assert window.limit_reached is expected_limit_reached


def test_unknown_status_string_keeps_the_window_but_not_a_fake_ok():
    quota = parse_opencode_go_usage(
        _usage_payload(rolling={"status": "throttling-soon", "percent": 30, "resetsAt": "2026-09-14T17:00:00Z"})
    )

    window = quota.window("five_hour")
    assert window.status == "unknown"
    assert window.percent_used == 30.0
    # Percent is still readable, so exhaustion is answerable.
    assert window.limit_reached is False


def test_unknown_status_without_percent_is_undeterminable_not_false():
    quota = parse_opencode_go_usage(_usage_payload(rolling={"status": "mystery", "resetsAt": None}))

    window = quota.window("five_hour")
    assert window.percent_used is None
    assert window.limit_reached is None


@pytest.mark.parametrize(
    "percent",
    [
        "45",  # string
        True,  # bool is an int subclass; must not read as 1%
        -1,  # out of range
        101,  # out of range
        float("nan"),
        float("inf"),
        None,
        {"value": 40},
    ],
)
def test_unusable_percent_becomes_unknown_never_clamped(percent):
    """Clamping would manufacture a confident empty-or-exhausted reading."""
    quota = parse_opencode_go_usage(
        _usage_payload(rolling={"status": "ok", "percent": percent, "resetsAt": "2026-09-14T17:00:00Z"})
    )

    window = quota.window("five_hour")
    assert window.percent_used is None
    assert window.resets_at == datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-09-14T17:00:00Z", datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc)),
        ("2026-09-14T17:00:00z", datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc)),
        ("2026-09-14T19:00:00+02:00", datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc)),
        # Naive input is assumed UTC rather than rejected.
        ("2026-09-14T17:00:00", datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc)),
        # Epoch seconds and milliseconds are both plausible for an unverified field.
        (1789405200, datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc)),
        (1789405200000, datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc)),
    ],
)
def test_resets_at_parsing(raw, expected):
    quota = parse_opencode_go_usage(_usage_payload(rolling={"status": "ok", "percent": 5, "resetsAt": raw}))

    assert quota.window("five_hour").resets_at == expected


@pytest.mark.parametrize("raw", ["", "   ", "not-a-date", 0, -5, True, [], {"at": "now"}])
def test_unparseable_resets_at_does_not_drop_the_window(raw):
    quota = parse_opencode_go_usage(_usage_payload(rolling={"status": "ok", "percent": 5, "resetsAt": raw}))

    window = quota.window("five_hour")
    assert window is not None
    assert window.resets_at is None
    assert window.percent_used == 5.0


def test_missing_window_is_omitted_not_zeroed():
    payload = _usage_payload()
    del payload["usage"]["weekly"]

    quota = parse_opencode_go_usage(payload)

    assert [window.key for window in quota.windows] == ["five_hour", "monthly"]
    assert quota.window("weekly") is None


@pytest.mark.parametrize("malformed", [None, "rate-limited", 42, [], [{"percent": 10}]])
def test_malformed_window_entry_is_omitted(malformed):
    quota = parse_opencode_go_usage(_usage_payload(weekly=malformed))

    assert quota.window("weekly") is None
    assert [window.key for window in quota.windows] == ["five_hour", "monthly"]


def test_window_with_nothing_usable_is_omitted():
    quota = parse_opencode_go_usage(_usage_payload(weekly={"other": "field"}))

    assert quota.window("weekly") is None


def test_usage_document_with_all_windows_unusable_parses_to_empty_not_error():
    """Upstream did answer with a usage document, so this is not "unavailable".

    Empty windows read as unknown downstream, never as zero usage.
    """
    quota = parse_opencode_go_usage({"usage": {"rolling": None, "weekly": "x", "monthly": 3}})

    assert quota.windows == ()
    assert quota.scope == "unknown"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "rate-limited",
        42,
        [],
        {},
        {"usage": None},
        {"usage": "ok"},
        {"usage": []},
        # An auth error body is a recognizable non-usage document.
        {"type": "error", "error": {"type": "AuthError", "message": "Missing API key."}},
    ],
)
def test_unrecognizable_envelope_raises(payload):
    with pytest.raises(OpenCodeGoQuotaParseError):
        parse_opencode_go_usage(payload)


def test_extra_upstream_windows_are_ignored_not_guessed():
    """A future upstream window we have no evidence for is not surfaced blind."""
    quota = parse_opencode_go_usage(
        _usage_payload(daily={"status": "ok", "percent": 10, "resetsAt": "2026-09-15T00:00:00Z"})
    )

    assert [window.key for window in quota.windows] == ["five_hour", "weekly", "monthly"]
