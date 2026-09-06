from __future__ import annotations

UNAVAILABLE_SELECTION_ERROR_CODES = frozenset(
    {
        "no_accounts",
        "no_plan_support_for_model",
        "additional_quota_data_unavailable",
        "quota_exhausted",
        "no_additional_quota_eligible_accounts",
    }
)


def status_for_error_fields(*, code: str | None, error_type: str | None) -> int:
    """Map an OpenAI-shape error code/type pair to its downstream HTTP status.

    This is the single classification every path must use when it needs a
    status for an error body it is about to emit, so the status line and the
    body can never disagree (an upstream ``usage_limit_reached`` stays a 429
    instead of being laundered into a 502 the client retries as a transport
    fault).
    """
    if code == "previous_response_not_found":
        return 502
    if code in UNAVAILABLE_SELECTION_ERROR_CODES:
        return 503
    if code in {"rate_limit_exceeded", "usage_limit_reached", "insufficient_quota"}:
        return 429
    if code in {"invalid_api_key", "invalid_authentication", "token_invalidated"}:
        return 401
    if code == "invalid_request_error":
        return 400
    if error_type == "authentication_error":
        return 401
    if error_type == "invalid_request_error":
        return 400
    if error_type in {"rate_limit_error", "usage_limit_reached", "insufficient_quota"}:
        return 429
    return 502
