from __future__ import annotations

from app.modules.proxy.sidecar_upstream_errors import (
    SIDECAR_UPSTREAM_AUTH_RETRY_AFTER_SECONDS,
    SIDECAR_UPSTREAM_UNAVAILABLE_CODE,
    SIDECAR_UPSTREAM_UNAVAILABLE_MESSAGE,
    client_facing_sidecar_error,
    is_sidecar_upstream_auth_failure,
)


def test_is_sidecar_upstream_auth_failure_only_401_403() -> None:
    assert is_sidecar_upstream_auth_failure(401)
    assert is_sidecar_upstream_auth_failure(403)
    assert not is_sidecar_upstream_auth_failure(400)
    assert not is_sidecar_upstream_auth_failure(429)
    assert not is_sidecar_upstream_auth_failure(500)
    assert not is_sidecar_upstream_auth_failure(503)


def test_client_facing_sidecar_error_remaps_missing_api_key_401() -> None:
    result = client_facing_sidecar_error(
        status_code=401,
        message="[401]: Missing API key",
        error_code="omniroute_sidecar_error",
        extra_headers={"x-ratelimit-remaining": "9"},
    )

    assert result.status_code == 503
    assert result.headers["Retry-After"] == str(SIDECAR_UPSTREAM_AUTH_RETRY_AFTER_SECONDS)
    assert result.headers["x-ratelimit-remaining"] == "9"
    assert result.content["error"]["code"] == SIDECAR_UPSTREAM_UNAVAILABLE_CODE
    assert result.content["error"]["message"] == SIDECAR_UPSTREAM_UNAVAILABLE_MESSAGE
    assert "Missing API key" not in result.content["error"]["message"]
    assert "[401]" not in result.content["error"]["message"]


def test_client_facing_sidecar_error_remaps_403() -> None:
    result = client_facing_sidecar_error(
        status_code=403,
        message="forbidden",
        error_code="openrouter_sidecar_error",
    )

    assert result.status_code == 503
    assert result.headers["Retry-After"] == str(SIDECAR_UPSTREAM_AUTH_RETRY_AFTER_SECONDS)
    assert result.content["error"]["code"] == SIDECAR_UPSTREAM_UNAVAILABLE_CODE


def test_client_facing_sidecar_error_passthrough_non_auth() -> None:
    body = {"error": {"message": "model overloaded", "type": "server_error", "code": "overloaded"}}
    result = client_facing_sidecar_error(
        status_code=529,
        message="model overloaded",
        error_code="omniroute_sidecar_error",
        body=body,
        extra_headers={"x-request-id": "abc"},
    )

    assert result.status_code == 529
    assert "Retry-After" not in result.headers
    assert result.headers["x-request-id"] == "abc"
    assert result.content == body


def test_client_facing_sidecar_error_wraps_when_body_not_envelope() -> None:
    result = client_facing_sidecar_error(
        status_code=502,
        message="bad gateway",
        error_code="claude_sidecar_error",
        body="not-json",
    )

    assert result.status_code == 502
    assert result.content["error"]["code"] == "claude_sidecar_error"
    assert result.content["error"]["message"] == "bad gateway"
