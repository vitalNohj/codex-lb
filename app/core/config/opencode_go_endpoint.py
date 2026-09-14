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

**What this must actually guarantee.** Every caller builds requests by plain
string concatenation - ``f"{base_url}/chat/completions"``, ``f"{base_url}/models"``,
``f"{base_url}/usage"``. So the question is not "does this string look like Go"
but "does ``<base>/<suffix>`` reach Go". Those differ, and two rounds of review
found the gap in successively subtler places:

``https://opencode.ai/zen/v1#/go/v1``
    A substring scan for ``/go/`` passes. Fragments are never transmitted, so
    the request path is ``/zen/v1``.
``https://opencode.ai/zen/go/v1#``
    Structural parsing sees an *empty* fragment and lets it through, but the
    concatenated suffix lands **inside** the fragment: the wire path stays
    ``/zen/go/v1`` and ``/chat/completions`` is never requested.
``https://opencode.ai/ZEN/GO/v1`` and ``https://opencode.ai/zen//go/v1``
    Case-folding and empty-segment removal make these compare equal to the
    canonical path, yet they are transmitted verbatim as ``/ZEN/GO/v1`` and
    ``/zen//go/v1``, which are different paths.

Rather than grow a third homemade URL resolver to chase these, this now does
what the evidence kept pointing at: **accept only the documented endpoint,
spelled canonically.** Go publishes exactly one base URL. There is no operator
need to write it a different way, and a validator that accepts only one string
cannot disagree with the wire. The one concession is a single optional trailing
slash, which every caller strips before concatenating.
"""

from __future__ import annotations

#: The documented Go base URL - the only accepted value.
OPENCODE_GO_DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"

OPENCODE_GO_BASE_URL_ERROR = (
    f"must be exactly the OpenCode Go endpoint {OPENCODE_GO_DEFAULT_BASE_URL} - "
    "an OpenCode Zen URL bills pay-as-you-go credits instead of the Go subscription"
)


def is_opencode_go_base_url(base_url: str) -> bool:
    """Return whether ``base_url`` is the OpenCode Go endpoint.

    Exact-match by design. Callers append path suffixes by string
    concatenation, so anything that is not literally the documented endpoint can
    produce a request that differs from what the string appears to say - through
    a fragment, a query, dot segments, an empty delimiter, case, or a doubled
    slash. Accepting one canonical spelling removes that entire class of
    disagreement instead of trying to enumerate it.

    Surrounding whitespace and one optional trailing slash are tolerated because
    they are transcription noise that provably cannot change the transmitted
    path: every caller applies ``rstrip("/")`` before concatenating.
    """

    return base_url.strip().rstrip("/") == OPENCODE_GO_DEFAULT_BASE_URL
