"""Is a base URL OpenCode **Go** rather than OpenCode Zen?

A leaf module with no imports on purpose. Three layers need this answer -
static settings validation, dashboard settings validation, and the HTTP client -
and ``app/core/config/settings.py`` sits below the clients package, so it cannot
reach up to ask. Putting the predicate here lets all three share one definition
instead of keeping two that can drift apart.

The distinction is financial, not cosmetic. Go is the $10/month subscription on
``/zen/go/v1``; Zen is pay-as-you-go credits on ``/zen/v1``. A Go key sent to the
Zen path bills credits rather than the subscription, and the two paths do not
even share per-endpoint authentication conventions.
"""

from __future__ import annotations

#: The documented Go base URL.
OPENCODE_GO_DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"

_OPENCODE_HOST_PREFIX = "https://opencode.ai"

OPENCODE_GO_BASE_URL_ERROR = (
    "must be an OpenCode Go endpoint such as https://opencode.ai/zen/go/v1 - "
    "an OpenCode Zen URL bills pay-as-you-go credits instead of the Go subscription"
)


def is_opencode_go_base_url(base_url: str) -> bool:
    """Return whether ``base_url`` addresses OpenCode Go.

    ``go`` is matched as a whole path *segment*, so ``/zen/go/v1`` passes while
    lookalikes such as ``/zen/v1/gold`` or ``/zen/going/v1`` do not. The host is
    checked too: a ``/go/`` path on some other host says nothing about which
    product bills the request.
    """

    normalized = base_url.strip().rstrip("/").lower()
    if not normalized.startswith(f"{_OPENCODE_HOST_PREFIX}/"):
        return False
    path = normalized[len(_OPENCODE_HOST_PREFIX) :]
    return "/go/" in f"{path}/"
