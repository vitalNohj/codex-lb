"""Remap sidecar upstream auth failures to client-retryable responses.

Also the one-shot provider retry shared by OpenAI-compatible sidecars: a
gateway or transport failure before any client byte is sent once more so the
upstream can choose another provider.

Once the proxy has accepted the client API key, an upstream 401/403 is a
provider-side credential/pool failure — never a client auth failure. Passing
those statuses through kills long-running clients that treat 401 as fatal.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TypeVar, cast

from app.core.errors import OpenAIErrorEnvelope, openai_error
from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping
from app.core.utils.request_id import get_request_id

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

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


def retry_sidecar_provider_failure(
    *,
    attempt: int,
    delivered: bool,
    status_code: int,
    retryable: bool = True,
) -> bool:
    """One immediate retry before any client byte on an upstream provider failure.

    Status >= 500 covers gateway timeouts (524), bad gateways (502), and
    transport failures reported as 503. A 4xx is the request itself. A stream
    that already yielded cannot be replaced. ``retryable`` is false for a
    failure that repeating the same payload would reproduce, such as an
    OpenCode Go body over the size limit.
    """

    return retryable and attempt == 0 and not delivered and status_code >= 500


def log_sidecar_provider_retry(*, provider: str, status_code: int, model: str) -> None:
    logger.warning(
        "%s provider failure status=%s model=%s request_id=%s; retrying once",
        provider,
        status_code,
        model,
        get_request_id(),
    )


async def call_with_sidecar_provider_retry(
    operation: Callable[[], Awaitable[_T]],
    *,
    provider: str,
    model: str,
) -> _T:
    """Run one sidecar call, and repeat it once after a provider failure."""

    try:
        return await operation()
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        retryable = getattr(exc, "retryable", True) is not False
        if not isinstance(status_code, int) or not retry_sidecar_provider_failure(
            attempt=0,
            delivered=False,
            status_code=status_code,
            retryable=retryable,
        ):
            raise
        log_sidecar_provider_retry(provider=provider, status_code=status_code, model=model)
        return await operation()


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
