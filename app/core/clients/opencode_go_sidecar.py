"""OpenCode Go native HTTPS client.

OpenCode Go is a $10/month subscription serving a curated set of open coding
models. Structurally it is another remote HTTPS provider, so this module follows
the OrcaRouter/OpenRouter client shape already proven in this repo rather than
introducing a new one.

Three things differ from those siblings and are load-bearing:

* **Go is not Zen.** The base URL is pinned to the ``/zen/go/v1`` path and
  validated to carry a ``/go/`` segment. A Go key used against the Zen base path
  bills PAYG credits instead of the subscription, and the two paths do not even
  agree on authentication conventions per endpoint. There is no fallback from
  Go to Zen or to any other paid upstream.
* **Per-request session identity.** Go asks for a stable ``x-opencode-session``
  per conversation. Unlike the sibling clients, whose header set is fixed for
  the life of the config, this client accepts per-request client headers and
  derives that one header from them. Nothing else from the inbound request is
  forwarded.
* **No published prices.** ``GET /zen/go/v1/models`` returns only
  ``{id, object, created, owned_by}``; there is no ``pricing`` block to parse,
  so this client publishes nothing to the runtime pricing registry. Pricing is
  resolved through the central external-pricing module instead.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast

import aiohttp

from app import __version__
from app.core.clients.claude_sidecar import SidecarModel, SidecarPrefix
from app.core.clients.http import lease_http_session
from app.core.config.opencode_go_endpoint import (
    OPENCODE_GO_DEFAULT_BASE_URL as _OPENCODE_GO_DEFAULT_BASE_URL,
)
from app.core.config.opencode_go_endpoint import (
    is_opencode_go_base_url as is_opencode_go_base_url,  # re-exported for existing importers
)
from app.core.conversation.opencode_go_session import apply_opencode_go_session_header
from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping

logger = logging.getLogger(__name__)

#: Pricing key space for this integration. Go serves ids such as ``glm-5.3``
#: that other integrations also list, at completely different economics (a flat
#: subscription rather than per-token PAYG), so a shared unqualified key space
#: would let whichever integration resolved last define the other's cost.
OPENCODE_GO_PRICING_PROVIDER = "opencode_go"

#: Routing/provider identity used by the unified sidecar resolver.
OPENCODE_GO_PROVIDER = "opencode_go"

#: The documented Go base URL. Zen lives at ``/zen/v1`` and is a different
#: product with different billing. Re-exported from the leaf endpoint module so
#: existing importers of this client keep working.
OPENCODE_GO_DEFAULT_BASE_URL = _OPENCODE_GO_DEFAULT_BASE_URL

#: Hard ceiling on a non-streaming body this client will hold in memory - the
#: models listing, a non-streaming chat completion, and the error body of a
#: failed streaming request. Chosen to match the sibling quota client's
#: ``MAX_USAGE_RESPONSE_BYTES`` so one size policy governs both, and generous
#: against the real catalogue (the live listing is a few KiB).
MAX_RESPONSE_BYTES = 1024 * 1024

#: Read granularity for the bounded read. Small enough that the overshoot past
#: the cap before detection stays negligible.
_READ_CHUNK_BYTES = 64 * 1024

#: Go's client obligations ask for a client-specific user agent rather than a
#: generic SDK or HTTP-library name. Third-party projects that sent a library
#: default had their background polls flagged by OpenCode; one worked around it
#: by impersonating a browser, which we deliberately do not copy.
OPENCODE_GO_USER_AGENT = f"codex-lb/{__version__}"


@dataclass(frozen=True, slots=True)
class OpenCodeGoSidecarConfig:
    enabled: bool
    base_url: str
    api_key: str | None
    prefixes: tuple[SidecarPrefix, ...]
    connect_timeout_seconds: float
    request_timeout_seconds: float
    models_cache_ttl_seconds: float
    full_models: tuple[str, ...] = ()


class OpenCodeGoSidecarError(Exception):
    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        body: JsonValue | None = None,
        retry_after: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.body = body
        #: Verbatim upstream ``Retry-After``. Preserved rather than recomputed:
        #: only the upstream knows when its own window reopens, and a guess that
        #: is too short turns one 429 into a retry storm.
        self.retry_after = retry_after


class OpenCodeGoSidecarUnavailableError(OpenCodeGoSidecarError):
    def __init__(self, message: str) -> None:
        super().__init__(503, message, body=None)


class OpenCodeGoSidecarResponseTooLargeError(OpenCodeGoSidecarError):
    """The upstream body exceeded :data:`MAX_RESPONSE_BYTES`.

    502 rather than 503: the upstream answered, and what it sent is unusable.
    ``retryable`` is false so the provider retry does not download that body
    again.
    """

    def __init__(self, message: str) -> None:
        super().__init__(502, message, body=None)
        self.retryable = False


class OpenCodeGoSidecarClient:
    def __init__(self, config: OpenCodeGoSidecarConfig) -> None:
        self._config = config
        self._models_cache: list[SidecarModel] | None = None
        self._models_cache_fetched_at: float = 0.0

    @property
    def config(self) -> OpenCodeGoSidecarConfig:
        return self._config

    @property
    def base_url(self) -> str:
        return self._config.base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return opencode_go_request_headers(self._config)

    def _timeout(self) -> aiohttp.ClientTimeout:
        return aiohttp.ClientTimeout(
            total=self._config.request_timeout_seconds,
            connect=self._config.connect_timeout_seconds,
            sock_connect=self._config.connect_timeout_seconds,
        )

    async def list_models(self) -> list[SidecarModel]:
        """Fetch the live Go model listing.

        Publishes nothing to the runtime pricing registry: the listing carries
        no rate fields at all, and writing an empty price for every id would
        assert "this model is free" where the truth is "this endpoint does not
        say".
        """

        url = f"{self.base_url}/models"
        try:
            async with lease_http_session() as session:
                async with session.get(url, headers=self._headers(), timeout=self._timeout()) as resp:
                    # Status first: an oversized *error* body must still surface
                    # the upstream's status and Retry-After, not be replaced by
                    # a generic 502. See ``_read_error_body``.
                    if resp.status >= 400:
                        raise _error_from_status(
                            resp.status,
                            await _read_error_body(resp),
                            resp.headers.get("Retry-After"),
                        )
                    data = await _read_response_json(resp)
        except OpenCodeGoSidecarError:
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
            raise OpenCodeGoSidecarUnavailableError(_transport_message(exc, "fetch OpenCode Go models")) from exc

        if not is_json_mapping(data):
            raise OpenCodeGoSidecarError(502, "Invalid response format from OpenCode Go models API", body=data)
        raw_models = data.get("data")
        if not isinstance(raw_models, list):
            raise OpenCodeGoSidecarError(502, "Missing 'data' key in OpenCode Go models response", body=data)

        models: list[SidecarModel] = []
        for entry in raw_models:
            if not is_json_mapping(entry):
                continue
            model_id = entry.get("id")
            if not isinstance(model_id, str) or not model_id:
                continue
            created = entry.get("created")
            owned_by = entry.get("owned_by")
            created_at = int(created) if isinstance(created, int | float) and not isinstance(created, bool) else None
            models.append(
                SidecarModel(
                    id=model_id,
                    created=created_at,
                    owned_by=owned_by if isinstance(owned_by, str) else "opencode",
                    raw=cast(Mapping[str, JsonValue], entry),
                    pricing=None,
                )
            )
        return models

    async def list_models_cached(self) -> list[SidecarModel]:
        now = time.monotonic()
        ttl = self._config.models_cache_ttl_seconds
        if self._models_cache is not None and ttl > 0 and now - self._models_cache_fetched_at < ttl:
            return list(self._models_cache)
        try:
            models = await self.list_models()
        except OpenCodeGoSidecarError as exc:
            # Never ``exc_info=True``: the traceback carries the upstream text
            # verbatim, and an upstream that echoes the Authorization header
            # would write the credential into the application log, which
            # runtime_logging redaction does not cover.
            detail = sanitize_opencode_go_message(exc.message, api_key=self._config.api_key)
            if self._models_cache is not None:
                logger.warning("using cached OpenCode Go models after refresh failure: %s", detail)
                return list(self._models_cache)
            logger.warning("OpenCode Go models unavailable: %s", detail)
            return []
        self._models_cache = list(models)
        self._models_cache_fetched_at = now
        return models

    async def chat_completion(
        self,
        payload: Mapping[str, JsonValue],
        *,
        client_headers: Mapping[str, str] | None = None,
    ) -> JsonValue:
        url = f"{self.base_url}/chat/completions"
        headers = apply_opencode_go_session_header(self._headers(), client_headers)
        try:
            async with lease_http_session() as session:
                async with session.post(
                    url,
                    headers=headers,
                    json=dict(payload),
                    timeout=self._timeout(),
                ) as resp:
                    if resp.status >= 400:
                        raise _error_from_status(
                            resp.status,
                            await _read_error_body(resp),
                            resp.headers.get("Retry-After"),
                        )
                    return await _read_response_json(resp)
        except OpenCodeGoSidecarError:
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
            raise OpenCodeGoSidecarUnavailableError(_transport_message(exc, "call OpenCode Go")) from exc

    @asynccontextmanager
    async def stream_chat_completion(
        self,
        payload: Mapping[str, JsonValue],
        *,
        client_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[AsyncIterator[bytes]]:
        url = f"{self.base_url}/chat/completions"
        headers = apply_opencode_go_session_header(self._headers(), client_headers)
        try:
            async with lease_http_session() as session:
                async with session.post(
                    url,
                    headers=headers,
                    json=dict(payload),
                    timeout=self._timeout(),
                ) as resp:
                    if resp.status >= 400:
                        raise _error_from_status(
                            resp.status,
                            await _read_error_body(resp),
                            resp.headers.get("Retry-After"),
                        )
                    yield resp.content.iter_chunked(8192)
        except OpenCodeGoSidecarError:
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
            raise OpenCodeGoSidecarUnavailableError(_transport_message(exc, "stream OpenCode Go")) from exc


def opencode_go_request_headers(config: OpenCodeGoSidecarConfig) -> dict[str, str]:
    """Outbound header set for any OpenCode Go request, foreground or background.

    Exposed as a module function, not just a client method, so a background poll
    owned by another lane (the ``/usage`` quota poller) sends the same user agent
    and the same auth scheme. Two header builders would let the user-agent
    obligation and the credential drift apart, which is exactly the failure that
    got other projects' background calls flagged.
    """

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": OPENCODE_GO_USER_AGENT,
    }
    api_key = (config.api_key or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


# Single-entry, config-keyed client cache. ``list_models_cached`` keeps its TTL
# state on the instance, so a client built inline per request could never hit
# that cache and every ``GET /v1/models`` would pay another upstream round trip.
#
# Holding exactly one entry - rather than a dict keyed by config - is what makes
# a settings change safe: any change to the base URL, API key, prefixes, or TTL
# produces a different ``OpenCodeGoSidecarConfig``, which evicts the previous
# client together with its cached models and its copy of the old credential.
_cached_client: OpenCodeGoSidecarClient | None = None
_cached_client_lock = threading.Lock()


def get_opencode_go_sidecar_client(config: OpenCodeGoSidecarConfig) -> OpenCodeGoSidecarClient:
    """Return a client whose models cache survives across requests."""

    global _cached_client
    with _cached_client_lock:
        cached = _cached_client
        if cached is not None and cached.config == config:
            return cached
        client = OpenCodeGoSidecarClient(config)
        _cached_client = client
        return client


def reset_opencode_go_sidecar_client_cache() -> None:
    """Drop the cached client (and the credential it holds)."""

    global _cached_client
    with _cached_client_lock:
        _cached_client = None


_REDACTION = "[redacted]"
# Characters that may appear *inside* a credential. Mirrors
# app/core/runtime_logging.py so the closing quote/brace of an echoed header
# survives while the credential does not.
_TOKEN_CHARS = r"A-Za-z0-9._~+/=-"
_CREDENTIAL_VALUE = rf"[{_TOKEN_CHARS}]+(?::[{_TOKEN_CHARS}]+)*"
_BEARER_TOKEN_RE = re.compile(rf"(?i)(bearer[\s:=]+){_CREDENTIAL_VALUE}")
# OpenCode issues keys with an ``sk-`` prefix and upstream text can echo them
# bare, with no ``Bearer`` in front ("Invalid API key: sk-...").
_OPENCODE_KEY_RE = re.compile(rf"(?i)sk-{_CREDENTIAL_VALUE}")
_WHITESPACE_RE = re.compile(r"\s")
# A configured value made only of letters is the one shape that can also occur
# as an ordinary word in upstream prose ("key" inside "Invalid API key"), where
# blanket redaction would corrupt the operator- and client-visible message.
# Every other shape - digits, punctuation, or mixed - cannot be a bare prose
# word and is treated as a secret whatever its length.
_ALPHABETIC_WORD_RE = re.compile(r"^[A-Za-z]+$")
_MIN_ALPHABETIC_CREDENTIAL_LENGTH = 16
_CREDENTIAL_LABEL_RE = r"(?i)((?:bearer|authorization|api[-_ ]?key|x-api-key)[\s:=\"']+)"
# Characters that may *end* a credential are not the same set as those that may
# appear inside one: upstream text echoes keys next to '=', ':', ',', '.',
# quotes and brackets, all of which delimit the token rather than continue it.
# Only an adjacent alphanumeric means the match is an interior slice of a longer
# word, which is the single case the boundary exists to reject.
_NOT_AFTER_TOKEN_CHAR = r"(?<![A-Za-z0-9])"
_NOT_BEFORE_TOKEN_CHAR = r"(?![A-Za-z0-9])"


def _looks_credential_bearing(value: str) -> bool:
    """Is this configured value shaped like a secret rather than ordinary text?

    Shape and length are combined, because either alone is too narrow. A short
    key is still a stored secret, and an upstream that echoes it bare would
    otherwise persist it to ``opencode_go_sidecar_last_health_message`` and
    ``request_logs.error_message`` and hand it back to the caller. Only a purely
    alphabetic value is ambiguous with prose, and there length decides.
    """

    if not value or _WHITESPACE_RE.search(value):
        return False
    if _ALPHABETIC_WORD_RE.match(value):
        return len(value) >= _MIN_ALPHABETIC_CREDENTIAL_LENGTH
    return True


def sanitize_opencode_go_message(message: str, *, api_key: str | None = None) -> str:
    """Strip the OpenCode Go credential out of an operator- or client-visible string.

    Shared by every path this integration uses to surface upstream text: the
    health check persists it to ``opencode_go_sidecar_last_health_message``,
    chat dispatch persists it to ``request_logs.error_message`` and hands it back
    to the calling API key, and the models refresh logs it.

    The configured key is matched exactly rather than pattern-guessed, but only
    as a whole token and only when it is credential-bearing or sits in a
    credential position, so a short configured value cannot garble unrelated
    words. The ``Bearer``/``sk-`` patterns run unconditionally and cover keys
    that are no longer the configured one.
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
    sanitized = _BEARER_TOKEN_RE.sub(rf"\g<1>{_REDACTION}", sanitized)
    return _OPENCODE_KEY_RE.sub(_REDACTION, sanitized)


def sanitize_opencode_go_error_body(body: JsonValue | None, *, api_key: str | None = None) -> JsonValue | None:
    """Sanitize every string inside an upstream error body.

    ``client_facing_sidecar_error`` relays the upstream body verbatim to the
    calling API key for non-401/403 statuses, so the credential has to be removed
    from the nested payload too, not only from the flattened message.
    """

    if isinstance(body, str):
        return sanitize_opencode_go_message(body, api_key=api_key)
    if isinstance(body, list):
        return [sanitize_opencode_go_error_body(entry, api_key=api_key) for entry in body]
    if is_json_mapping(body):
        return {key: sanitize_opencode_go_error_body(value, api_key=api_key) for key, value in body.items()}
    return body


def _declared_length_over_cap(resp: aiohttp.ClientResponse) -> bool:
    """Does upstream declare a length already known to be too large?

    An advisory fast path only. A chunked or compressed response carries no
    usable length and a hostile one can lie, so this never substitutes for
    counting the bytes actually read.
    """

    raw = resp.headers.get("Content-Length")
    if raw is None:
        return False
    try:
        return int(raw) > MAX_RESPONSE_BYTES
    except (TypeError, ValueError):
        return False


async def _read_error_body(resp: aiohttp.ClientResponse) -> JsonValue:
    """Read an error body under the same cap, without losing the status.

    The cap still applies - an error body is exactly as attacker-influenced as a
    success body - but exceeding it must not *replace* the upstream's answer.
    ``_read_response_json`` raises 502, which would erase a 429 and its
    ``Retry-After``, and this integration's 429 handling depends on relaying
    that header verbatim; a dropped one turns a rate limit into a retry storm
    against a subscription with hard dollar caps. A 401/403 would likewise be
    downgraded to a generic upstream fault, losing the credential-problem
    signal the dashboard and the caller both act on.

    So an oversized or unreadable error body degrades to "no body" and lets
    :func:`_error_from_status` fall back to its ``HTTP <status>`` message. The
    status and ``Retry-After`` come from the headers and are unaffected.
    """

    try:
        return await _read_response_json(resp)
    except OpenCodeGoSidecarError:
        return None


async def _read_response_json(resp: aiohttp.ClientResponse) -> JsonValue:
    """Read a non-streaming body under a hard byte cap.

    Streams and counts rather than calling ``resp.text()``: that buffers the
    whole body before anything can inspect its size, so an upstream that is
    hostile, misconfigured, or actually a captive portal decides how much memory
    this process allocates. Counting decoded chunks bounds the real in-memory
    cost, including chunked and compressed transfers where ``Content-Length`` is
    absent or misleading.

    Mirrors the contract the sibling quota client already enforces
    (``MAX_USAGE_RESPONSE_BYTES`` in ``app/core/clients/opencode_go.py``) rather
    than inventing a second size policy.
    """

    if _declared_length_over_cap(resp):
        raise OpenCodeGoSidecarResponseTooLargeError(
            f"OpenCode Go response is too large (declared over {MAX_RESPONSE_BYTES} bytes)"
        )

    chunks: list[bytes] = []
    total = 0
    try:
        async for chunk in resp.content.iter_chunked(_READ_CHUNK_BYTES):
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                # Stop pulling immediately: the point is to not allocate the
                # rest. The partial body is dropped rather than reported - it is
                # attacker-influenced and cannot be a valid document.
                raise OpenCodeGoSidecarResponseTooLargeError(
                    f"OpenCode Go response is too large (exceeded {MAX_RESPONSE_BYTES} bytes)"
                )
            chunks.append(chunk)
    except OpenCodeGoSidecarError:
        raise
    except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
        raise OpenCodeGoSidecarUnavailableError(
            f"Failed to read OpenCode Go response: {exc.__class__.__name__}"
        ) from exc

    if not chunks:
        return {}
    text = b"".join(chunks).decode("utf-8", errors="replace")
    if not text:
        return {}
    try:
        return cast(JsonValue, json.loads(text))
    except json.JSONDecodeError:
        return {"message": text}


def _error_from_status(status_code: int, body: JsonValue, retry_after: str | None = None) -> OpenCodeGoSidecarError:
    message = f"OpenCode Go returned HTTP {status_code}"
    if is_json_mapping(body):
        error = body.get("error")
        if is_json_mapping(error):
            error_message = error.get("message")
            if isinstance(error_message, str) and error_message:
                message = error_message
        else:
            body_message = body.get("message")
            if isinstance(body_message, str) and body_message:
                message = body_message
    return OpenCodeGoSidecarError(status_code, message, body=body, retry_after=retry_after)


def _transport_message(exc: BaseException, action: str) -> str:
    detail = str(exc) or exc.__class__.__name__
    return f"Failed to {action}: {detail}"
