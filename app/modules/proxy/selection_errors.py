from __future__ import annotations

import time
from typing import Protocol

from app.core.clients.proxy import ProxyResponseError
from app.core.errors import OpenAIErrorEnvelope, ResponseFailedEvent, openai_error, response_failed_event
from app.core.resilience.overload import is_local_overload_error_code

USAGE_LIMIT_REACHED = "usage_limit_reached"

# Stable fail-closed contract for continuity-bound follow-ups whose required
# owner account is unavailable. The error code/body never changes between the
# instant-502 path and the bounded-hold-expiry path; only the status code and
# retry hint differ.
CONTINUITY_OWNER_UNAVAILABLE_CODE = "previous_response_owner_unavailable"
CONTINUITY_OWNER_UNAVAILABLE_ERROR_TYPE = "server_error"
# Sensible client retry hint emitted with the 503 when the bounded hold
# expires; matches the drain window scale rather than the hold scale.
CONTINUITY_OWNER_HOLD_RETRY_AFTER_SECONDS = 15


class SelectionFailure(Protocol):
    error_message: str | None
    error_code: str | None
    resets_at: int | None


def selection_failure_response(selection: SelectionFailure) -> tuple[int, OpenAIErrorEnvelope]:
    """Map an account-selection failure to its externally visible HTTP response.

    The ``usage_limit_reached`` mapping is strictly for upstream usage/quota
    exhaustion of the whole eligible pool. Local capacity codes (account caps,
    admission gates, fair-share throttles) resolve against the canonical
    ``LOCAL_OVERLOAD_CODES`` registry so they keep their stable 429
    ``rate_limit_error`` contract and are never reclassified as upstream usage
    exhaustion or collapsed into a generic 503.
    """
    code = selection.error_code or "no_accounts"
    message = selection.error_message or "No active accounts available"
    if code == USAGE_LIMIT_REACHED:
        return (
            429,
            openai_error(
                code,
                message,
                error_type=USAGE_LIMIT_REACHED,
                resets_at=selection.resets_at,
            ),
        )
    if is_local_overload_error_code(code):
        return 429, openai_error(code, message, error_type="rate_limit_error")
    return 503, openai_error(code, message)


def previous_response_owner_unavailable_error(
    *,
    hold_expired: bool = False,
    message: str | None = None,
) -> ProxyResponseError:
    """Build the continuity-owner-unavailable error for the current mode.

    Without ``hold_expired`` this is the long-standing instant 502. With
    ``hold_expired`` the bounded transient-drain hold ran to expiry, so the
    same body/code is delivered as a retryable 503 with a ``Retry-After``
    hint instead of the instant 502.
    """
    if hold_expired:
        return ProxyResponseError(
            503,
            openai_error(
                CONTINUITY_OWNER_UNAVAILABLE_CODE,
                message
                or (
                    "Required previous-response owner is temporarily draining; "
                    f"retry after {CONTINUITY_OWNER_HOLD_RETRY_AFTER_SECONDS} seconds"
                ),
                error_type=CONTINUITY_OWNER_UNAVAILABLE_ERROR_TYPE,
                resets_at=int(time.time()) + CONTINUITY_OWNER_HOLD_RETRY_AFTER_SECONDS,
            ),
            retry_after_seconds=CONTINUITY_OWNER_HOLD_RETRY_AFTER_SECONDS,
        )
    return ProxyResponseError(
        502,
        openai_error(
            CONTINUITY_OWNER_UNAVAILABLE_CODE,
            message or "Required previous-response owner is unavailable",
            error_type=CONTINUITY_OWNER_UNAVAILABLE_ERROR_TYPE,
        ),
    )


def previous_response_owner_unavailable_failed_event(
    *,
    response_id: str | None,
    message: str | None = None,
    hold_expired: bool = False,
) -> ResponseFailedEvent:
    """Build the SSE/websocket ``response.failed`` event for this failure.

    Keeps the stable error code; when the bounded hold expired the event
    carries the retry hint so clients reconnect after the drain window.
    """
    if hold_expired:
        return response_failed_event(
            code=CONTINUITY_OWNER_UNAVAILABLE_CODE,
            message=message
            or (
                "Required previous-response owner is temporarily draining; "
                f"retry after {CONTINUITY_OWNER_HOLD_RETRY_AFTER_SECONDS} seconds"
            ),
            error_type=CONTINUITY_OWNER_UNAVAILABLE_ERROR_TYPE,
            response_id=response_id,
            resets_at=int(time.time()) + CONTINUITY_OWNER_HOLD_RETRY_AFTER_SECONDS,
        )
    return response_failed_event(
        code=CONTINUITY_OWNER_UNAVAILABLE_CODE,
        message=message or "Required previous-response owner is unavailable",
        error_type=CONTINUITY_OWNER_UNAVAILABLE_ERROR_TYPE,
        response_id=response_id,
    )
