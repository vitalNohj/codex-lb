"""HTTP client for the OpenCode Go subscription usage endpoint.

Scope is deliberately one read: ``GET <base_url>/usage``. Inference transport for
OpenCode Go belongs to the provider integration, not here, and this module must
never grow a chat path - a quota surface that can issue inference is a quota
surface that can burn the subscription it reports on.

Identity follows the Go docs' client obligation ("Identify itself with its own
user agent, such as ``my-coding-agent/1.0``, rather than a generic SDK or
HTTP-library name"). The Python prior art sends a spoofed Chrome User-Agent to
dodge a Cloudflare challenge; that is not reused. If OpenCode challenges an
honest agent, the correct answer is an honest failure the operator can see, not a
fake browser identity.

``x-opencode-session`` is not sent. The docs ask for a stable session ID "for
each conversation so we can optimize routing and prompt caching"; a usage read is
not a conversation, and no reviewed source establishes that ``/usage`` requires
or interprets one. Synthesizing an ID would be an invented protocol detail.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import cast

import aiohttp

from app import __version__
from app.core.clients.http import lease_http_session
from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping

DEFAULT_OPENCODE_GO_BASE_URL = "https://opencode.ai/zen/go/v1"

# Where a non-JSON response body is parked. Deliberately not ``message``, so a
# raw HTML page is never promoted into an operator-visible error string.
NON_JSON_BODY_KEY = "__non_json_body__"
# A body we could not parse is diagnostic only, and an upstream error page can be
# megabytes; keep just enough to recognize it.
_NON_JSON_SNIPPET_LENGTH = 120

# Honest, client-specific identity per the Go docs' obligation.
OPENCODE_GO_USER_AGENT = f"codex-lb/{__version__} (+https://github.com/vitalNohj/codex-lb)"


@dataclass(frozen=True, slots=True)
class OpenCodeGoConfig:
    """Everything the usage read depends on.

    Frozen and compared by value so the service's single-entry cache is
    invalidated by *any* config change - crucially including the API key, so a
    re-keyed subscription can never read the previous subscription's numbers.
    """

    enabled: bool
    base_url: str
    api_key: str | None
    connect_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 10.0


class OpenCodeGoError(Exception):
    """An upstream usage read failed. ``message`` is always sanitized."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class OpenCodeGoUnavailableError(OpenCodeGoError):
    """Transport-level failure: timeout, connection error, or unreadable body."""

    def __init__(self, message: str) -> None:
        super().__init__(503, message)


class OpenCodeGoClient:
    """Issues exactly one request: the usage read.

    Stateless by design - freshness, single-flight and last-good live in the
    service, so this object can be constructed per call without losing cache
    behavior.
    """

    def __init__(self, config: OpenCodeGoConfig) -> None:
        self._config = config

    @property
    def config(self) -> OpenCodeGoConfig:
        return self._config

    @property
    def base_url(self) -> str:
        return self._config.base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        api_key = (self._config.api_key or "").strip()
        if not api_key:
            # Unreachable through the service, which gates on the key first.
            # Guarded anyway so no future caller can send an unauthenticated
            # probe that upstream would see as a malformed client.
            raise OpenCodeGoError(401, "OpenCode Go API key is not configured")
        return {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": OPENCODE_GO_USER_AGENT,
        }

    def _timeout(self) -> aiohttp.ClientTimeout:
        return aiohttp.ClientTimeout(
            total=self._config.request_timeout_seconds,
            connect=self._config.connect_timeout_seconds,
            sock_connect=self._config.connect_timeout_seconds,
        )

    async def fetch_usage(self) -> JsonValue:
        """One bounded GET of the usage endpoint.

        Raises ``OpenCodeGoError`` (with the upstream status) or
        ``OpenCodeGoUnavailableError``; both carry a sanitized message.
        """
        url = f"{self.base_url}/usage"
        headers = self._headers()
        try:
            async with lease_http_session() as session:
                async with session.get(url, headers=headers, timeout=self._timeout()) as response:
                    body = await _read_response_json(response)
                    if response.status >= 400:
                        raise _error_from_status(response.status, body, api_key=self._config.api_key)
                    return body
        except OpenCodeGoError:
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
            raise OpenCodeGoUnavailableError(
                sanitize_opencode_go_message(
                    f"Failed to fetch OpenCode Go usage: {exc or exc.__class__.__name__}",
                    api_key=self._config.api_key,
                )
            ) from exc


async def _read_response_json(response: aiohttp.ClientResponse) -> JsonValue:
    try:
        text = await response.text()
    except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
        raise OpenCodeGoUnavailableError(
            f"Failed to read OpenCode Go usage response: {exc.__class__.__name__}"
        ) from exc
    if not text:
        return {}
    try:
        return cast(JsonValue, json.loads(text))
    except json.JSONDecodeError:
        # Keep the text under a private key rather than ``message``: an HTML
        # error page or captive-portal notice would otherwise be adopted
        # verbatim as the operator-visible message, and it can never be a usage
        # document either, so the parser rejects it as an unrecognized envelope.
        return {NON_JSON_BODY_KEY: text}


def _error_from_status(status_code: int, body: JsonValue, *, api_key: str | None) -> OpenCodeGoError:
    message = f"OpenCode Go usage endpoint returned HTTP {status_code}"
    if is_json_mapping(body):
        error = body.get("error")
        if is_json_mapping(error):
            detail = error.get("message")
            if isinstance(detail, str) and detail.strip():
                message = detail.strip()
        else:
            detail = body.get("message")
            if isinstance(detail, str) and detail.strip():
                message = detail.strip()
            else:
                raw = body.get(NON_JSON_BODY_KEY)
                if isinstance(raw, str) and raw.strip():
                    # Keep the status as the message and append a bounded
                    # snippet, so the operator sees which of the two it was
                    # without a page of markup in the dashboard.
                    snippet = " ".join(raw.split())[:_NON_JSON_SNIPPET_LENGTH]
                    message = f"{message}: {snippet}"
    return OpenCodeGoError(status_code, sanitize_opencode_go_message(message, api_key=api_key))


_REDACTION = "[redacted]"
# Mirrors the shape used by the OrcaRouter sanitizer: the character class that
# may appear *inside* a credential is wider than the one that may terminate it,
# so an echoed header's closing quote or brace survives while the token does not.
_TOKEN_CHARS = r"A-Za-z0-9._~+/=-"
_CREDENTIAL_VALUE = rf"[{_TOKEN_CHARS}]+(?::[{_TOKEN_CHARS}]+)*"
_BEARER_TOKEN_RE = re.compile(rf"(?i)(bearer[\s:=]+){_CREDENTIAL_VALUE}")
_WHITESPACE_RE = re.compile(r"\s")
_ALPHABETIC_WORD_RE = re.compile(r"^[A-Za-z]+$")
_MIN_ALPHABETIC_CREDENTIAL_LENGTH = 16
_CREDENTIAL_LABEL_RE = r"(?i)((?:bearer|authorization|api[-_ ]?key)[\s:=\"']+)"
_NOT_AFTER_TOKEN_CHAR = r"(?<![A-Za-z0-9])"
_NOT_BEFORE_TOKEN_CHAR = r"(?![A-Za-z0-9])"


def _looks_credential_bearing(value: str) -> bool:
    """Is this configured value shaped like a secret rather than ordinary prose?

    Nothing constrains the shape of an OpenCode Go key, so any value carrying a
    digit or punctuation is treated as a secret at any length. Only a purely
    alphabetic value is ambiguous with a word an upstream might echo ("key" in
    "Invalid API key"), and there length decides: short stays label-gated so the
    upstream message is returned intact, long is redacted wherever it appears.
    """
    if not value or _WHITESPACE_RE.search(value):
        return False
    if _ALPHABETIC_WORD_RE.match(value):
        return len(value) >= _MIN_ALPHABETIC_CREDENTIAL_LENGTH
    return True


def sanitize_opencode_go_message(message: str, *, api_key: str | None = None) -> str:
    """Strip the OpenCode Go credential out of an operator-visible string.

    Every path that surfaces upstream text - the quota response's ``message`` and
    ``staleReason``, and any log line - goes through here, so an upstream that
    echoes the Authorization header cannot leak the key to the dashboard.

    The configured key is matched exactly but only as a whole token, so a short
    configured value cannot garble unrelated words; the ``Bearer`` pattern runs
    unconditionally and also covers a key that is no longer the configured one.
    """
    sanitized = message
    configured_key = (api_key or "").strip()
    if configured_key:
        token = re.escape(configured_key)
        if _looks_credential_bearing(configured_key):
            sanitized = re.sub(
                rf"{_NOT_AFTER_TOKEN_CHAR}{token}{_NOT_BEFORE_TOKEN_CHAR}",
                _REDACTION,
                sanitized,
            )
        else:
            sanitized = re.sub(
                rf"{_CREDENTIAL_LABEL_RE}{token}{_NOT_BEFORE_TOKEN_CHAR}",
                rf"\g<1>{_REDACTION}",
                sanitized,
            )
    return _BEARER_TOKEN_RE.sub(rf"\g<1>{_REDACTION}", sanitized)
