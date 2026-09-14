"""The single seam between the quota lane and the OpenCode Go backend lane.

The backend integration owns the settings columns, the credential, the decrypt
step and the outbound header set. This module binds to the symbols it publishes
and adds nothing of its own:

- ``opencode_go_sidecar_config_from_settings`` / ``load_opencode_go_sidecar_config``
  (``app/modules/proxy/opencode_go_sidecar_dispatch``) - the one audited place the
  Go credential is decrypted.
- ``opencode_go_request_headers`` (``app/core/clients/opencode_go_sidecar``) - the
  one header builder, deliberately exposed as a module function so this
  background ``/usage`` poll sends the same user agent and auth scheme as the
  chat path. Two builders would let the Go docs' user-agent obligation and the
  credential drift apart.
- ``sanitize_opencode_go_message`` - so both lanes redact identically.

There is deliberately **no** fallback column spelling and **no** local decryptor.
An earlier draft of the quota contract asked for un-prefixed ``opencode_go_*``
columns while the backend ships ``opencode_go_sidecar_*``; reading the wrong
spelling would have reported ``not_configured`` against a fully configured,
working integration - silent, and contradicting the Settings screen the operator
is looking at. MAIN settled the spelling: the backend's ``opencode_go_sidecar_*``
columns and its existing config/header helpers are authoritative. Importing the
loader rather than re-reading columns makes that mismatch structurally
impossible to reintroduce.
"""

from __future__ import annotations

from app.core.clients.opencode_go import OpenCodeGoConfig
from app.core.clients.opencode_go_sidecar import (
    OpenCodeGoSidecarConfig,
    opencode_go_request_headers,
    sanitize_opencode_go_message,
)
from app.db.models import DashboardSettings
from app.modules.proxy.opencode_go_sidecar_dispatch import (
    opencode_go_sidecar_config_from_settings,
)

__all__ = [
    "build_request_headers",
    "quota_config_from_settings",
    "sanitize_message",
    "to_quota_config",
]


def to_quota_config(config: OpenCodeGoSidecarConfig) -> OpenCodeGoConfig:
    """Narrow the backend's sidecar config to what the usage read needs.

    The backend config also carries routing concerns (model prefixes, full-model
    lists, the models cache TTL) that a quota read has no business consuming.
    Narrowing keeps the quota cache key to the three fields that actually change
    a ``/usage`` result, while still deriving all three from the backend loader.

    Timeouts are carried across rather than re-specified: an operator who
    shortens the Go timeouts means it for this poll too.
    """
    return OpenCodeGoConfig(
        enabled=bool(config.enabled),
        base_url=config.base_url,
        api_key=(config.api_key or "").strip() or None,
        connect_timeout_seconds=config.connect_timeout_seconds,
        request_timeout_seconds=config.request_timeout_seconds,
    )


def quota_config_from_settings(settings: DashboardSettings) -> OpenCodeGoConfig:
    """Resolve the usage config from the backend-owned settings row.

    Decryption happens inside the backend's loader, never here. A decrypt
    failure surfaces there as ``api_key=None``, which this lane reports as
    ``not_configured`` without contacting upstream - a key we cannot read is not
    a key we should send.
    """
    return to_quota_config(opencode_go_sidecar_config_from_settings(settings))


def build_request_headers(config: OpenCodeGoConfig) -> dict[str, str]:
    """Outbound headers for the usage read, from the backend's builder.

    The backend builder omits ``Authorization`` when no key is set. A quota poll
    must never issue an unauthenticated probe - upstream would read it as a
    malformed client - so a missing credential is a programming error here, and
    the service gates on the key long before this point.
    """
    api_key = (config.api_key or "").strip()
    if not api_key:
        raise ValueError("OpenCode Go API key is not configured")

    headers = dict(
        opencode_go_request_headers(
            OpenCodeGoSidecarConfig(
                enabled=config.enabled,
                base_url=config.base_url,
                api_key=api_key,
                prefixes=(),
                connect_timeout_seconds=config.connect_timeout_seconds,
                request_timeout_seconds=config.request_timeout_seconds,
                models_cache_ttl_seconds=0.0,
            )
        )
    )
    if "Authorization" not in headers:
        raise ValueError("OpenCode Go request headers are missing authorization")
    # A usage read sends no body; advertising a request content type would be a
    # small lie about a GET. Everything else from the backend builder - notably
    # the user agent and auth scheme - is preserved verbatim.
    headers.pop("Content-Type", None)
    return headers


def sanitize_message(message: str, *, api_key: str | None = None) -> str:
    """Strip the credential from an operator-visible string."""
    return sanitize_opencode_go_message(message, api_key=api_key)
