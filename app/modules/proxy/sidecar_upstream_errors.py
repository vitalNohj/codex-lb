"""Remap sidecar upstream auth failures to client-retryable responses.

Once the proxy has accepted the client API key, an upstream 401/403 is a
provider-side credential/pool failure — never a client auth failure. Passing
those statuses through kills long-running clients that treat 401 as fatal.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from app.core.errors import OpenAIErrorEnvelope, openai_error
from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping

SIDECAR_UPSTREAM_AUTH_STATUS_CODES = frozenset({401, 403})
SIDECAR_UPSTREAM_AUTH_RETRY_AFTER_SECONDS = 60
SIDECAR_UPSTREAM_UNAVAILABLE_CODE = "sidecar_upstream_unavailable"
SIDECAR_UPSTREAM_UNAVAILABLE_MESSAGE = (
    "Upstream provider temporarily unavailable; retry later."
)


@dataclass(frozen=True, slots=True)
class SidecarClientError:
    status_code: int
    content: OpenAIErrorEnvelope
    headers: dict[str, str]


def is_sidecar_upstream_auth_failure(status_code: int) -> bool:
    return status_code in SIDECAR_UPSTREAM_AUTH_STATUS_CODES


def client_facing_sidecar_error(
    *,
    status_code: int,
    message: str,
    error_code: str,
    body: JsonValue | None = None,
    extra_headers: Mapping[str, str] | None = None,
) -> SidecarClientError:
    """Build the client-facing sidecar error after client auth already succeeded."""
    headers = dict(extra_headers or {})
    if is_sidecar_upstream_auth_failure(status_code):
        headers["Retry-After"] = str(SIDECAR_UPSTREAM_AUTH_RETRY_AFTER_SECONDS)
        return SidecarClientError(
            status_code=503,
            content=openai_error(
                SIDECAR_UPSTREAM_UNAVAILABLE_CODE,
                SIDECAR_UPSTREAM_UNAVAILABLE_MESSAGE,
                error_type="upstream_error",
            ),
            headers=headers,
        )

    return SidecarClientError(
        status_code=status_code,
        content=_passthrough_or_wrap(body=body, error_code=error_code, message=message),
        headers=headers,
    )


def _passthrough_or_wrap(
    *,
    body: JsonValue | None,
    error_code: str,
    message: str,
) -> OpenAIErrorEnvelope:
    if is_json_mapping(body):
        error = body.get("error")
        if is_json_mapping(error):
            error_message = error.get("message")
            if isinstance(error_message, str) and error_message:
                return cast(OpenAIErrorEnvelope, body)
    return openai_error(error_code, message, error_type="upstream_error")
