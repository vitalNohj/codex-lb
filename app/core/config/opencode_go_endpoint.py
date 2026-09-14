"""Is a base URL OpenCode **Go** rather than OpenCode Zen?

A leaf module with no app imports on purpose. Three layers need this answer -
static settings validation, dashboard settings validation, and the HTTP client -
and ``app/core/config/settings.py`` sits below the clients package, so it cannot
reach up to ask. Putting the predicate here lets all three share one definition
instead of keeping copies that can drift apart.

The distinction is financial, not cosmetic. Go is the $10/month subscription on
``/zen/go/v1``; Zen is pay-as-you-go credits on ``/zen/v1``. A Go key sent to the
Zen path bills credits rather than the subscription, and the two paths do not
even share per-endpoint authentication conventions.

**This check must answer for the request that will actually be sent, not for the
string an operator typed.** An earlier version substring-scanned the raw URL for
``/go/``, which several shapes defeat while still targeting Zen on the wire:

``https://opencode.ai/zen/v1#/go/v1``
    A fragment is never transmitted. The request path is ``/zen/v1``.
``https://opencode.ai/zen/v1?x=/go/v1``
    A query string is not the path. The request path is ``/zen/v1``.
``https://opencode.ai/zen/go/../v1``
    Dot segments resolve away. The request path is ``/zen/v1``.

So the URL is parsed structurally and the *resolved path* is compared against the
one Go endpoint. Anything carrying a component that cannot appear in a plain Go
base URL - userinfo, a port, a query, a fragment - is rejected outright rather
than normalized away, because there is no legitimate reason for one and each is
a way to make the string disagree with the wire.
"""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

#: The documented Go base URL.
OPENCODE_GO_DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"

#: Exact host. Matched whole, so ``opencode.ai.evil.com`` cannot pass.
_OPENCODE_HOST = "opencode.ai"

#: The one path Go is served on, as resolved segments.
_GO_PATH_SEGMENTS = ("zen", "go", "v1")

OPENCODE_GO_BASE_URL_ERROR = (
    "must be exactly the OpenCode Go endpoint https://opencode.ai/zen/go/v1 - "
    "an OpenCode Zen URL bills pay-as-you-go credits instead of the Go subscription"
)


def _resolved_segments(path: str) -> list[str] | None:
    """Resolve a URL path into the segments a server would see.

    Splitting happens on the **raw** path and each segment is decoded
    afterwards, which is the order the wire uses. Decoding first would be wrong
    in both directions: ``%2F`` is a literal slash *inside* one segment, not a
    separator, and aiohttp transmits it still encoded - so treating it as a
    boundary would accept ``/zen/go%2Fv1`` as Go when the request actually asks
    for a single segment named ``go/v1`` that Go does not serve.

    ``..`` is applied so a path climbing back out of ``/go/`` is judged by where
    it lands. ``None`` means the path escaped its own root, which is malformed
    rather than merely unexpected.
    """

    segments: list[str] = []
    for raw_segment in path.split("/"):
        if raw_segment in ("", "."):
            continue
        if raw_segment == "..":
            if not segments:
                return None
            segments.pop()
            continue
        decoded = unquote(raw_segment)
        # A decoded separator would have changed the segment count, so the
        # string no longer describes the path it appears to. Reject rather than
        # guess which reading the upstream will take.
        if "/" in decoded:
            return None
        segments.append(decoded)
    return segments


def is_opencode_go_base_url(base_url: str) -> bool:
    """Return whether ``base_url`` addresses OpenCode Go on the wire.

    Deliberately strict: it answers "will the request this configures reach the
    Go subscription endpoint", so it accepts only the documented endpoint and
    rejects every shape whose transmitted path would differ from its appearance.
    """

    candidate = base_url.strip()
    if not candidate:
        return False

    try:
        parts = urlsplit(candidate)
    except ValueError:
        return False

    # Scheme and host are the identity of the endpoint. HTTPS only: the
    # credential is a bearer token and must not be sent in the clear.
    if parts.scheme.lower() != "https":
        return False
    if (parts.hostname or "").lower() != _OPENCODE_HOST:
        return False

    # None of these can appear in a legitimate Go base URL, and each is a way to
    # make the string look like Go while the request goes elsewhere. Rejected
    # rather than stripped, so a surprising value is never silently "corrected".
    if parts.username or parts.password or parts.query or parts.fragment:
        return False
    try:
        if parts.port is not None:
            return False
    except ValueError:
        # A non-numeric port is malformed; treat it as a rejection, not a crash.
        return False

    segments = _resolved_segments(parts.path)
    if segments is None:
        return False
    return tuple(segment.lower() for segment in segments) == _GO_PATH_SEGMENTS
