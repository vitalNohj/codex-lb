"""Vendor limit-evidence parsing and scope classification.

The load-bearing property here is CONSERVATISM: a rejection is only ever
called ``shared`` when the vendor explicitly said so. Most of these tests
exist to prove the code does NOT jump to that conclusion, because doing so
would park a healthy provider and skip models that would have passed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.free_model_discovery.limits import (
    MAX_HONOURED_WAIT_SECONDS,
    RateLimitEvidence,
    cap_wait,
    classify_scope,
    describe_wait,
    evidence_from_response,
    group_wait_seconds,
    parse_retry_after,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)


# --- Retry-After: RFC 9110 delta-seconds or HTTP-date ---------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("120", 120.0),
        ("0", 0.0),
        ("  45  ", 45.0),
        ("30.5", 30.5),
        (None, None),
        ("", None),
        ("soon", None),
        ("-5", None),  # negative is malformed, not "retry immediately"
        ("nan", None),
        ("inf", None),
    ],
)
def test_parse_retry_after_delta_seconds(raw, expected):
    assert parse_retry_after(raw, now=_NOW) == expected


def test_parse_retry_after_accepts_an_http_date():
    """RFC 9110 permits an absolute date; OpenRouter documents seconds, but a
    conformant intermediary may still emit a date."""

    future = _NOW + timedelta(seconds=90)
    raw = future.strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert parse_retry_after(raw, now=_NOW) == pytest.approx(90.0, abs=1.0)


def test_parse_retry_after_treats_a_past_date_as_zero_not_negative():
    past = _NOW - timedelta(hours=1)
    raw = past.strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert parse_retry_after(raw, now=_NOW) == 0.0


def test_parse_retry_after_clamps_an_extreme_value():
    assert parse_retry_after("999999999", now=_NOW) == MAX_HONOURED_WAIT_SECONDS


# --- header extraction -----------------------------------------------------


def test_headers_are_read_case_insensitively():
    evidence = evidence_from_response(
        headers={"RETRY-AFTER": "60", "X-RateLimit-Remaining": "0", "x-ratelimit-limit": "50"},
        body=None,
        now=_NOW,
    )
    assert evidence.retry_after_seconds == 60.0
    assert evidence.remaining == 0
    assert evidence.limit == 50


def test_only_whitelisted_fields_are_captured():
    """Nothing outside the allowlist may become discovery state - no
    credential, cookie, account identifier or arbitrary vendor text."""

    evidence = evidence_from_response(
        headers={
            "Authorization": "Bearer sk-secret-value",
            "Set-Cookie": "session=abc",
            "X-Account-Id": "acct_12345",
            "Retry-After": "30",
        },
        body={"error": {"message": "Provider returned error", "metadata": {"raw": "sk-leaked-key"}}},
        now=_NOW,
    )
    serialized = repr(evidence)
    assert "sk-secret-value" not in serialized
    assert "sk-leaked-key" not in serialized
    assert "acct_12345" not in serialized
    assert "session=abc" not in serialized
    assert evidence.retry_after_seconds == 30.0


def test_conflicting_header_and_body_hints_honour_the_longer_wait():
    evidence = evidence_from_response(headers={"Retry-After": "10"}, body={"error": {"retry_after": 300}}, now=_NOW)
    assert evidence.retry_after_seconds == 300.0


def test_reset_header_is_kept_as_opaque_text_not_a_timestamp():
    """OpenRouter documents the header family but not the unit of Reset, so
    converting it to a time would be invented."""

    evidence = evidence_from_response(headers={"X-RateLimit-Reset": "1789000000000"}, body=None, now=_NOW)
    assert evidence.reset_hint == "1789000000000"
    assert evidence.retry_after_seconds is None


# --- scope classification: the conservative core ---------------------------


def test_explicit_platform_rate_limit_is_shared():
    evidence = evidence_from_response(
        headers={"Retry-After": "3600"},
        body={"error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}}},
        now=_NOW,
    )
    assert classify_scope(evidence) == "shared"


def test_upstream_attribution_is_model_scoped():
    evidence = evidence_from_response(
        headers=None,
        body={
            "error": {
                "code": 429,
                "message": "Provider returned error",
                "metadata": {"provider_name": "SomeUpstream", "provider_code": 429},
            }
        },
        now=_NOW,
    )
    assert classify_scope(evidence) == "model"


def test_provider_overloaded_is_model_scoped():
    evidence = evidence_from_response(
        headers=None, body={"error": {"metadata": {"error_type": "provider_overloaded"}}}, now=_NOW
    )
    assert classify_scope(evidence) == "model"


def test_upstream_attribution_wins_over_a_platform_code():
    """If the vendor named an upstream backend, the rejection is that
    backend's - even alongside a rate-limit code."""

    evidence = evidence_from_response(
        headers=None,
        body={"error": {"metadata": {"error_type": "rate_limit_exceeded", "provider_name": "Up"}}},
        now=_NOW,
    )
    assert classify_scope(evidence) == "model"


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"error": {"code": 429, "message": "Provider returned error"}},
        {"error": {"code": 429, "message": "Too Many Requests"}},
        {"error": {"code": 402, "message": "Insufficient credits"}},
        {"error": {"metadata": {"error_type": "unmapped"}}},
    ],
)
def test_ambiguous_rejections_stay_unknown(body):
    """The whole point. A bare 429/402 or a generic message proves nothing
    about scope, so discovery must not claim it did."""

    assert classify_scope(evidence_from_response(headers=None, body=body, now=_NOW)) == "unknown"


def test_remaining_zero_alone_does_not_prove_a_shared_limit():
    """`Remaining: 0` names neither the bucket that emptied nor its window."""

    evidence = evidence_from_response(
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Limit": "50"}, body=None, now=_NOW
    )
    assert evidence.remaining == 0
    assert classify_scope(evidence) == "unknown"


def test_retry_after_alone_is_waiting_guidance_not_scope():
    evidence = evidence_from_response(headers={"Retry-After": "600"}, body=None, now=_NOW)
    assert evidence.retry_after_seconds == 600.0
    assert classify_scope(evidence) == "unknown"


# --- waiting arithmetic ----------------------------------------------------


def test_a_vendor_wait_longer_than_the_cap_is_honoured_in_full():
    """A heuristic cap must never shorten a real vendor instruction."""

    evidence = RateLimitEvidence(retry_after_seconds=1800.0)
    assert cap_wait(40.0, evidence, cap_seconds=600.0) == 1800.0


def test_the_cap_still_bounds_the_heuristic_when_no_vendor_hint_exists():
    assert cap_wait(5000.0, RateLimitEvidence(), cap_seconds=600.0) == 600.0


def test_vendor_wait_shorter_than_the_heuristic_does_not_speed_us_up():
    evidence = RateLimitEvidence(retry_after_seconds=5.0)
    assert cap_wait(120.0, evidence, cap_seconds=600.0) == 120.0


def test_group_wait_requires_a_published_window():
    assert group_wait_seconds(RateLimitEvidence()) is None
    assert group_wait_seconds(RateLimitEvidence(retry_after_seconds=90.0)) == 90.0


# --- operator text ---------------------------------------------------------


def test_wait_text_never_invents_a_countdown_for_an_unknown_reset():
    text = describe_wait("shared", RateLimitEvidence(reset_hint="1789000000000"))
    assert "1789000000000" not in text
    assert "not published" in text


def test_wait_text_names_the_scope_honestly():
    assert "scope unknown" in describe_wait("unknown", RateLimitEvidence())
    assert "Provider-wide" in describe_wait("shared", RateLimitEvidence(retry_after_seconds=60.0))
    assert "upstream" in describe_wait("model", RateLimitEvidence(retry_after_seconds=60.0))


def test_wait_text_reports_a_published_wait():
    assert "1h" in describe_wait("shared", RateLimitEvidence(retry_after_seconds=3600.0))
    assert "90s" not in describe_wait("shared", RateLimitEvidence(retry_after_seconds=3600.0))


# --- non-finite header values ---------------------------------------------


@pytest.mark.parametrize("raw", ["inf", "-inf", "Infinity", "nan", "1e400"])
def test_non_finite_header_values_never_raise(raw):
    """An allowlisted header is upstream-controlled text.

    ``int(float("inf"))`` raises ``OverflowError``, which is neither
    ``TypeError`` nor ``ValueError``. Escaping here would abort evidence
    extraction and take down the whole discovery run through the driver's
    terminal failure path - a hostile or buggy header must never do that.
    """

    evidence = evidence_from_response(
        headers={"X-RateLimit-Remaining": raw, "X-RateLimit-Limit": raw}, body=None, now=_NOW
    )
    assert evidence.remaining is None
    assert evidence.limit is None
    assert classify_scope(evidence) == "unknown"
