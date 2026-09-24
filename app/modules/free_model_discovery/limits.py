"""Vendor rate-limit evidence: what the response actually proved.

Pure functions, no I/O. Two jobs, deliberately kept apart because conflating
them is the bug this module exists to prevent:

* **How long to wait** - ``retry_after_seconds``, taken only from signals the
  vendor documents as a wait instruction.
* **What was limited** - ``LimitScope``, which is ``shared`` ONLY when the
  provider explicitly attributed the rejection to its own platform/account
  limit rather than to an upstream model backend.

The second is not derivable from the first, nor from the HTTP status, nor from
how many 429s arrived in a row. OpenRouter documents that a 429 "can come from
two places": its own platform limits, or "the upstream provider ... In this
case ``error.metadata.provider_code`` carries the provider's original error
code when available."
(https://openrouter.ai/docs/api_reference/limits)

So ``Provider returned error``, a bare 429, a bare 402, a run of consecutive
429s, and ``X-RateLimit-Remaining: 0`` on its own all leave the scope
``unknown``. Treating any of them as account-wide would park a healthy
provider and skip candidate models that would have passed - strictly worse
than spending a few extra probes.

``X-RateLimit-Reset`` is captured but deliberately NOT converted into a
countdown: OpenRouter documents the header family's existence without
specifying the unit of ``Reset`` (epoch seconds, epoch millis, or delta), so
any conversion would be invented. It is retained as opaque diagnostic text and
reported as an unknown reset instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Literal

from app.core.utils.json_guards import JsonValue, is_json_mapping

# ``shared``  - the vendor said ITS OWN platform/account/key allowance was hit.
# ``model``   - the vendor attributed the rejection to an upstream backend.
# ``unknown`` - nothing in the documented contract establishes either.
LimitScope = Literal["shared", "model", "unknown"]

# Documented typed codes. https://openrouter.ai/docs/api_reference/errors-and-debugging
_PLATFORM_RATE_LIMIT_TYPES = frozenset({"rate_limit_exceeded"})
_UPSTREAM_TYPES = frozenset({"provider_overloaded", "provider_unavailable"})

# Never wait longer than this on one vendor instruction. A hostile or buggy
# upstream must not be able to park discovery for a week; the run deadline and
# the operator's cancel both still apply on top of this.
MAX_HONOURED_WAIT_SECONDS = 6 * 60 * 60.0

_RETRY_AFTER_HEADER = "retry-after"
_LIMIT_HEADER = "x-ratelimit-limit"
_REMAINING_HEADER = "x-ratelimit-remaining"
_RESET_HEADER = "x-ratelimit-reset"

# Only these response headers are ever read. Everything else - and every raw
# body - is discarded at the boundary, so no credential, prompt or account
# identifier can reach discovery state through this path. The sidecar clients
# enforce the same allowlist at the socket; this tuple documents what this
# module will consume and keeps the two in step through a shared test.
CAPTURED_HEADERS: tuple[str, ...] = (_RETRY_AFTER_HEADER, _LIMIT_HEADER, _REMAINING_HEADER, _RESET_HEADER)

_RESET_TEXT_MAX_CHARS = 32


@dataclass(frozen=True, slots=True)
class RateLimitEvidence:
    """What a rejection response actually established. All fields optional."""

    # Seconds the vendor instructed us to wait, when it gave a usable one.
    retry_after_seconds: float | None = None
    # Opaque, untranslated ``X-RateLimit-Reset`` text, for operator display
    # only. Never used as a timestamp - the unit is not documented.
    reset_hint: str | None = None
    remaining: int | None = None
    limit: int | None = None
    # The vendor's own typed code, when it published one.
    error_type: str | None = None
    # True when the vendor attributed the failure to an upstream backend.
    upstream_attributed: bool = False

    @property
    def has_retry_instruction(self) -> bool:
        return self.retry_after_seconds is not None


def _header(headers: Mapping[str, str] | None, name: str) -> str | None:
    """Case-insensitive lookup. Field names are case-insensitive per RFC 9110,
    and a plain dict from a test double or a non-aiohttp transport will not be
    a case-insensitive multidict."""

    if not headers:
        return None
    direct = headers.get(name)
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == name and isinstance(value, str) and value.strip():
            return value.strip()
    return None


def parse_retry_after(raw: str | None, *, now: datetime | None = None) -> float | None:
    """RFC 9110 ``Retry-After``: delta-seconds OR an HTTP-date.

    Returns a non-negative wait in seconds, or ``None`` when the value is
    missing, malformed, negative, or already in the past. A past date means
    "retry now", which is a zero wait rather than a negative one.
    """

    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None

    try:
        seconds = float(text)
    except ValueError:
        pass
    else:
        # Reject NaN/inf, which float() happily accepts from "nan"/"inf".
        if seconds != seconds or seconds in (float("inf"), float("-inf")):
            return None
        if seconds < 0:
            return None
        return min(seconds, MAX_HONOURED_WAIT_SECONDS)

    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    delta = (when - reference).total_seconds()
    if delta <= 0:
        return 0.0
    return min(delta, MAX_HONOURED_WAIT_SECONDS)


def _parse_int(raw: str | None) -> int | None:
    """Parse an allowlisted counter header defensively.

    ``int(float("inf"))`` raises ``OverflowError``, which is neither
    ``TypeError`` nor ``ValueError``, so a header of ``inf`` or ``1e400`` would
    escape evidence extraction and reach the driver's terminal failure path -
    killing the whole run over an upstream-controlled string. Non-finite values
    are rejected outright, and ``OverflowError`` is caught as a backstop.
    """

    if raw is None:
        return None
    try:
        value = float(raw)
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _body_retry_after(body: JsonValue | None) -> float | None:
    """Some routers echo a retry hint in the error body instead of a header."""

    if not is_json_mapping(body):
        return None
    error = body.get("error")
    container = error if is_json_mapping(error) else body
    for key in ("retry_after", "retryAfter", "retry_after_seconds"):
        value = container.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            if value != value or value in (float("inf"), float("-inf")) or value < 0:
                continue
            return min(float(value), MAX_HONOURED_WAIT_SECONDS)
        if isinstance(value, str):
            parsed = parse_retry_after(value)
            if parsed is not None:
                return parsed
    return None


def _error_metadata(body: JsonValue | None) -> Mapping[str, JsonValue] | None:
    if not is_json_mapping(body):
        return None
    error = body.get("error")
    if not is_json_mapping(error):
        return None
    metadata = error.get("metadata")
    return metadata if is_json_mapping(metadata) else None


def evidence_from_response(
    *, headers: Mapping[str, str] | None, body: JsonValue | None, now: datetime | None = None
) -> RateLimitEvidence:
    """Extract only the whitelisted retry/scope fields from a rejection.

    The raw body and the remaining headers are not retained anywhere: this is
    the single point where vendor response data is allowed to become discovery
    state, and it is an explicit allowlist rather than a redaction pass.
    """

    header_wait = parse_retry_after(_header(headers, _RETRY_AFTER_HEADER), now=now)
    body_wait = _body_retry_after(body)
    # Conflicting hints: honour the LONGER one. Retrying earlier than a wait
    # the vendor actually asked for is the failure mode that gets a key
    # throttled harder, so disagreement resolves toward patience.
    if header_wait is None:
        retry_after = body_wait
    elif body_wait is None:
        retry_after = header_wait
    else:
        retry_after = max(header_wait, body_wait)

    reset_raw = _header(headers, _RESET_HEADER)
    reset_hint = reset_raw[:_RESET_TEXT_MAX_CHARS] if reset_raw else None

    metadata = _error_metadata(body)
    error_type: str | None = None
    upstream_attributed = False
    if metadata is not None:
        raw_type = metadata.get("error_type")
        if isinstance(raw_type, str) and raw_type.strip():
            error_type = raw_type.strip()[:64]
        # Presence of provider attribution is the vendor telling us which
        # upstream backend refused - documented for the upstream-provider case.
        for key in ("provider_code", "provider_name"):
            value = metadata.get(key)
            if value is not None and not (isinstance(value, str) and not value.strip()):
                upstream_attributed = True

    return RateLimitEvidence(
        retry_after_seconds=retry_after,
        reset_hint=reset_hint,
        remaining=_parse_int(_header(headers, _REMAINING_HEADER)),
        limit=_parse_int(_header(headers, _LIMIT_HEADER)),
        error_type=error_type,
        upstream_attributed=upstream_attributed,
    )


def classify_scope(evidence: RateLimitEvidence) -> LimitScope:
    """What the vendor EXPLICITLY attributed the rejection to.

    Conservative by construction. ``shared`` requires the vendor's own typed
    platform rate-limit code with no upstream attribution alongside it.

    Deliberately NOT sufficient for ``shared``, each of which was considered
    and rejected:

    * a 429 or 402 status on its own - documented as ambiguous between
      platform and upstream;
    * ``X-RateLimit-Remaining: 0`` on its own - it names no scope or window,
      and the header family is not documented per-limit;
    * a generic message such as ``Provider returned error``;
    * several 429s in a row, which cannot distinguish one exhausted account
      from several independently busy upstream backends.
    """

    if evidence.upstream_attributed:
        return "model"
    if evidence.error_type:
        if evidence.error_type in _PLATFORM_RATE_LIMIT_TYPES:
            return "shared"
        if evidence.error_type in _UPSTREAM_TYPES:
            return "model"
    return "unknown"


def describe_wait(scope: LimitScope, evidence: RateLimitEvidence, *, next_attempt_at: datetime | None = None) -> str:
    """One short, operator-facing sentence. Never invents a countdown."""

    if scope == "shared":
        subject = "Provider-wide limit reached"
    elif scope == "model":
        subject = "This model's upstream is rate limited"
    else:
        subject = "Rate limited; scope unknown"

    if evidence.retry_after_seconds is not None:
        return f"{subject}; provider asked to wait {_humanize(evidence.retry_after_seconds)}"
    if next_attempt_at is not None:
        return f"{subject}; retrying on the usual backoff"
    if evidence.reset_hint is not None:
        # The unit is undocumented, so the raw token is shown as-is and
        # explicitly labelled unknown rather than rendered as a time.
        return f"{subject}; reset time not published by the provider"
    return f"{subject}; no retry time published"


def _humanize(seconds: float) -> str:
    total = int(round(seconds))
    if total < 60:
        return f"{total}s"
    if total < 3600:
        minutes, rest = divmod(total, 60)
        return f"{minutes}m" if rest == 0 else f"{minutes}m {rest}s"
    hours, rest = divmod(total, 3600)
    minutes = rest // 60
    return f"{hours}h" if minutes == 0 else f"{hours}h {minutes}m"


def group_wait_seconds(evidence: RateLimitEvidence) -> float | None:
    """Wait to apply to the whole provider group for an explicit shared limit.

    ``None`` when the vendor published no usable window - in that case the
    caller must fall back to ordinary per-item backoff rather than inventing
    one, because a made-up group pause is indistinguishable to the operator
    from a real one.
    """

    if evidence.retry_after_seconds is None:
        return None
    return max(0.0, min(evidence.retry_after_seconds, MAX_HONOURED_WAIT_SECONDS))


def cap_wait(heuristic_seconds: float, evidence: RateLimitEvidence, *, cap_seconds: float) -> float:
    """Combine the adaptive backoff with a vendor instruction.

    The heuristic cap bounds only the heuristic. A genuine vendor wait longer
    than the cap is honoured in full: silently retrying at the cap would beat
    the provider's own instruction and is exactly what earns a harder throttle.
    """

    bounded_heuristic = min(heuristic_seconds, cap_seconds)
    if evidence.retry_after_seconds is None:
        return bounded_heuristic
    return max(bounded_heuristic, min(evidence.retry_after_seconds, MAX_HONOURED_WAIT_SECONDS))
