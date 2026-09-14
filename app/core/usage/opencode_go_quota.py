"""Parse the OpenCode Go subscription usage payload into typed windows.

Pure transformation, no I/O: ``app/core/clients/opencode_go.py`` owns the HTTP
round trip and ``app/modules/opencode_go/service.py`` owns caching and freshness.

Evidence for the response shape
-------------------------------
``GET https://opencode.ai/zen/go/v1/usage`` is **undocumented**. OpenCode's Go
docs say only "You can track your current usage in the console". The route's
existence is probed (it answers 401 ``AuthError`` without a key while the Zen
sibling path answers an HTML 404); its *content* comes from two independent MIT
implementations that agree:

- ``diegosouzapw/OmniRoute@release/v3.8.51``
  ``open-sse/services/opencodeQuotaFetcher.ts``
- ``kartikkabadi/opencode-go-proxy@main``
  ``src/opencode_go_proxy/usage_poller.py`` (MIT, Copyright (c) 2026 Kartik Kabadi)

Both read ``payload["usage"]`` -> ``{rolling, weekly, monthly}``; OmniRoute
additionally validates each window as ``{status, percent, resetsAt}`` with
``status`` in ``{"ok", "rate-limited"}`` and ``percent`` in 0..100. No code here
is copied from either project - this is an independent implementation written to
this repo's conventions, and the citation records where the *shape* evidence came
from.

What is deliberately NOT inferred
---------------------------------
- **Scope.** The payload carries three unlabelled windows and no model key, so
  whether the numbers are account-wide or per-model is unknown. ``QuotaScope`` is
  reported as ``unknown`` rather than guessed; the docs define limits *per model*,
  which makes "account total" an unsafe label, and nothing in the payload makes
  "per model" a safe one either.
- **Dollar caps.** The docs publish per-model monthly dollar caps ($15/$30/$60)
  and the 20%/50%/100% window split. Spend against them is not in this payload,
  so no cap is ever converted into a remaining percentage.
- **Percent direction.** ``percent`` is treated as *used* because OmniRoute
  derives exhaustion from ``percent === 100``, which is only consistent with the
  used direction. That is a single-source inference, so the parser exposes
  ``percent_used`` only and never derives a "remaining" figure, which would give
  the inference a false second confirmation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping

QuotaWindowKey = Literal["five_hour", "weekly", "monthly"]
QuotaWindowStatus = Literal["ok", "rate_limited", "unknown"]
QuotaScope = Literal["unknown", "account", "per_model"]

# Upstream key -> codex-lb window key, in the order the dashboard renders them.
#
# ``rolling`` maps to ``five_hour`` because the Go docs define exactly one
# sub-daily window and it is the 5-hour one ("5-hour - 20% of the monthly
# limit"). The binding of the *name* ``rolling`` to that window is an inference,
# so every parsed window keeps ``upstream_key`` verbatim and the dashboard
# contract exposes it; a future authenticated capture can then be diffed against
# this mapping without ambiguity.
WINDOW_KEYS: tuple[tuple[str, QuotaWindowKey], ...] = (
    ("rolling", "five_hour"),
    ("weekly", "weekly"),
    ("monthly", "monthly"),
)

# Upstream status strings we have evidence for. Anything else yields
# ``"unknown"`` - the window is still returned, because its percent and reset
# may remain usable, but its status is not silently coerced to "ok".
_UPSTREAM_STATUSES: Mapping[str, QuotaWindowStatus] = {
    "ok": "ok",
    "rate-limited": "rate_limited",
}


@dataclass(frozen=True, slots=True)
class OpenCodeGoQuotaWindow:
    """One usage window.

    ``percent_used`` is 0..100 in the *used* direction, or ``None`` when upstream
    omitted it or sent something unusable. ``None`` means unknown - never zero
    and never full.
    """

    key: QuotaWindowKey
    upstream_key: str
    status: QuotaWindowStatus
    percent_used: float | None
    resets_at: datetime | None

    @property
    def limit_reached(self) -> bool | None:
        """Is this window exhausted? ``None`` when undeterminable.

        ``rate_limited`` is authoritative on its own: upstream saying the window
        is rate limited means exhausted whatever the percent says. Otherwise a
        percent of 100 means exhausted. With neither signal readable the answer
        is unknown, which must not collapse to ``False``.
        """
        if self.status == "rate_limited":
            return True
        if self.percent_used is None:
            return None if self.status == "unknown" else False
        return self.percent_used >= 100.0


@dataclass(frozen=True, slots=True)
class OpenCodeGoQuota:
    """A parsed usage payload.

    ``windows`` holds only the windows that parsed; a missing or malformed
    upstream entry is omitted rather than represented with zeros, so consumers
    must handle a partial list.
    """

    windows: tuple[OpenCodeGoQuotaWindow, ...]
    scope: QuotaScope = "unknown"

    @property
    def model_breakdown_available(self) -> bool:
        """Does upstream supply per-model usage? Always ``False`` today.

        Kept as a property over ``scope`` rather than a stored flag so the two
        can never disagree, and so the Accounts model selector appears
        automatically if upstream ever grows the dimension.
        """
        return self.scope == "per_model"

    def window(self, key: QuotaWindowKey) -> OpenCodeGoQuotaWindow | None:
        for window in self.windows:
            if window.key == key:
                return window
        return None


class OpenCodeGoQuotaParseError(Exception):
    """The payload is not a usage response we recognize.

    Raised instead of returning an empty quota so the caller can distinguish
    "upstream answered with something else entirely" (unavailable) from
    "upstream answered with a usage document whose windows were unusable".
    """


def parse_opencode_go_usage(payload: JsonValue) -> OpenCodeGoQuota:
    """Parse an upstream ``/usage`` body.

    Raises ``OpenCodeGoQuotaParseError`` when the envelope is unrecognizable.
    A recognizable envelope whose windows are all malformed parses to an empty
    ``windows`` tuple: upstream did answer with a usage document, and empty
    windows read as *unknown* downstream, never as zero usage.
    """
    if not is_json_mapping(payload):
        raise OpenCodeGoQuotaParseError("usage response was not a JSON object")
    usage = payload.get("usage")
    if not is_json_mapping(usage):
        raise OpenCodeGoQuotaParseError("usage response had no 'usage' object")

    windows: list[OpenCodeGoQuotaWindow] = []
    for upstream_key, key in WINDOW_KEYS:
        window = _parse_window(usage.get(upstream_key), key=key, upstream_key=upstream_key)
        if window is not None:
            windows.append(window)
    # Scope stays ``unknown``: the payload has no model dimension to promote it
    # to ``per_model`` and no evidence that the windows are account-wide.
    return OpenCodeGoQuota(windows=tuple(windows), scope="unknown")


def _parse_window(
    raw: JsonValue,
    *,
    key: QuotaWindowKey,
    upstream_key: str,
) -> OpenCodeGoQuotaWindow | None:
    if not is_json_mapping(raw):
        return None
    status = _parse_status(raw.get("status"))
    percent_used = _parse_percent(raw.get("percent"))
    resets_at = _parse_timestamp(raw.get("resetsAt"))
    if status is None and percent_used is None and resets_at is None:
        # Nothing usable in the object at all; omit rather than emit a window
        # that reads as "0% used, no reset".
        return None
    return OpenCodeGoQuotaWindow(
        key=key,
        upstream_key=upstream_key,
        status=status if status is not None else "unknown",
        percent_used=percent_used,
        resets_at=resets_at,
    )


def _parse_status(value: JsonValue) -> QuotaWindowStatus | None:
    if not isinstance(value, str):
        return None
    return _UPSTREAM_STATUSES.get(value.strip().lower(), "unknown")


def _parse_percent(value: JsonValue) -> float | None:
    """0..100 used-percent, or ``None`` when unusable.

    ``bool`` is excluded explicitly because it is an ``int`` subclass and
    ``True`` would otherwise parse as 1%. Out-of-range values are rejected
    rather than clamped: clamping a negative or 3000 into 0 or 100 would
    manufacture a confident "empty" or "exhausted" reading out of a value we
    plainly do not understand.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    percent = float(value)
    if percent != percent or percent in (float("inf"), float("-inf")):
        return None
    if percent < 0.0 or percent > 100.0:
        return None
    return percent


def _parse_timestamp(value: JsonValue) -> datetime | None:
    """Parse ``resetsAt`` into an aware UTC datetime.

    Accepts ISO 8601 (with ``Z``) and epoch seconds/milliseconds, because the
    upstream representation is unverified and both are plausible; anything
    unparseable yields ``None`` so the window still renders without a reset
    rather than being dropped entirely. What ``resetsAt`` is *aligned to*
    (rolling from first use, or a fixed calendar boundary) is unverified and
    deliberately not interpreted here - the value is passed through.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return _timestamp_from_epoch(float(value))
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# Epoch values below this are seconds; at or above it they are milliseconds.
# 1e11 seconds is year 5138, and 1e11 milliseconds is 1973, so no realistic
# reset timestamp is ambiguous across the boundary.
_EPOCH_MILLISECOND_THRESHOLD = 1e11


def _timestamp_from_epoch(value: float) -> datetime | None:
    if value <= 0.0 or value != value:
        return None
    seconds = value / 1000.0 if value >= _EPOCH_MILLISECOND_THRESHOLD else value
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
