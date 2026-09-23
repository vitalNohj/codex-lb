from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import AsyncIterator, Collection, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast
from urllib.parse import urlsplit

import aiohttp

from app.core.clients.claude_sidecar import SidecarModel, SidecarPrefix, parse_sidecar_per_token_usd
from app.core.clients.http import lease_http_session
from app.core.types import JsonValue
from app.core.usage.pricing import ModelPrice
from app.core.usage.runtime_pricing import get_runtime_pricing_registry
from app.core.utils.json_guards import is_json_mapping

logger = logging.getLogger(__name__)

# The only response headers ever copied off a rejection, lowercased. An
# allowlist, not a redaction pass: anything not named here never leaves the
# transport boundary, so no cookie, authorization echo or account identifier
# can reach a surface that renders provider text.
#
# Defined here rather than imported from the discovery module: a core HTTP
# client must not depend on a feature module, and these are ordinary HTTP
# rate-limit headers rather than anything discovery-specific.
RATE_LIMIT_HEADERS: frozenset[str] = frozenset(
    {"retry-after", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset"}
)

# Rate-limit header values are short tokens; cap them so a hostile upstream
# cannot push unbounded text into an exception that reaches operator surfaces.
_HEADER_VALUE_MAX_CHARS = 64


class OpenAICompatBaseUrlError(ValueError):
    """A configured base URL is not a shape this client will send a key to."""


def normalize_openai_compat_base_url(value: str) -> str:
    """Return the canonical form of a configured base URL, or raise.

    This feature deliberately accepts **arbitrary** OpenAI-compatible hosts, so
    the host itself cannot be pinned. What *is* checkable is the shape, and the
    shape decides where the operator's bearer token is sent once ``/models`` or
    ``/chat/completions`` is appended:

    * **Userinfo** (``https://attacker@host/v1``) makes aiohttp authenticate to
      one identity while the configured key rides along in the ``Authorization``
      header; it is never meaningful for these APIs.
    * **Query and fragment** survive the append as ``/v1?x=y/models``, so the
      request no longer targets the path the operator reviewed - and a fragment
      truncates the appended path entirely.
    * **Dot segments** (``/v1/../../admin``) resolve at the wire, so what the
      dashboard shows is not what is called. Percent-encoded dot segments
      (``%2e%2e``) and backslashes have to be rejected too, not just the literal
      spelling: the HTTP client canonicalizes the URL *after* this check, so
      ``https://host/v1/%2e%2e/%2e%2e/admin`` plus the appended ``/models``
      leaves as ``https://host/admin/models``. A literal-only check reads as a
      defence while letting the same redirection through, which is worse than no
      check. Any ``%`` in the path is therefore refused rather than decode-and-
      re-inspected: these are API base URLs, so no legitimate one needs
      percent-encoding, and a decode-then-check loop has to be exactly right
      about double encoding to be safe.

    Rejecting rather than silently rewriting is deliberate: a URL the operator
    did not mean is a credential-destination mistake, and a save-time error is
    the only place it can still be corrected. The scheme and host are
    case-normalized because both are case-insensitive per RFC 3986, so two
    spellings of one endpoint must not read as two different endpoints.
    """

    candidate = value.strip()
    if not candidate:
        raise OpenAICompatBaseUrlError("base_url must not be blank")
    parts = urlsplit(candidate)
    if parts.scheme.lower() not in {"http", "https"}:
        raise OpenAICompatBaseUrlError("base_url must be an http(s) URL")
    if "@" in parts.netloc:
        raise OpenAICompatBaseUrlError("base_url must not contain userinfo")
    if parts.query:
        raise OpenAICompatBaseUrlError("base_url must not contain a query string")
    if parts.fragment:
        raise OpenAICompatBaseUrlError("base_url must not contain a fragment")
    try:
        hostname = parts.hostname
        port = parts.port
    except ValueError as exc:  # malformed IPv6 literal or non-numeric port
        raise OpenAICompatBaseUrlError("base_url authority is not valid") from exc
    if not hostname:
        raise OpenAICompatBaseUrlError("base_url must contain a host")
    path = parts.path.rstrip("/")
    if "%" in path:
        raise OpenAICompatBaseUrlError("base_url path must not contain percent-encoded characters")
    if "\\" in path:
        raise OpenAICompatBaseUrlError("base_url path must not contain backslashes")
    if any(segment in {".", ".."} for segment in path.split("/")):
        raise OpenAICompatBaseUrlError("base_url path must not contain '.' or '..' segments")
    if "//" in path:
        raise OpenAICompatBaseUrlError("base_url path must not contain empty segments")
    scheme = parts.scheme.lower()
    # ``hostname`` already lowercases and strips the brackets from an IPv6
    # literal, so put them back rather than reusing the raw netloc (which may
    # carry the original casing).
    host = f"[{hostname}]" if ":" in hostname else hostname
    authority = f"{host}:{port}" if port is not None else host
    return f"{scheme}://{authority}{path}"


@dataclass(frozen=True, slots=True)
class OpenAICompatSidecarConfig:
    endpoint_id: str
    name: str
    enabled: bool
    base_url: str
    api_key: str | None
    prefixes: tuple[SidecarPrefix, ...]
    connect_timeout_seconds: float
    request_timeout_seconds: float
    models_cache_ttl_seconds: float
    full_models: tuple[str, ...] = ()
    default_reasoning_effort: str | None = None

    @property
    def provider_id(self) -> str:
        return f"openai_compat:{self.endpoint_id}"


class OpenAICompatSidecarError(Exception):
    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        body: JsonValue | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.body = body
        # Only the documented rate-limit/retry headers, copied out at the
        # boundary. Free-model discovery needs ``Retry-After`` and the
        # ``X-RateLimit-*`` family to tell a provider-wide limit from an
        # upstream one; keeping the whole header map would drag cookies and
        # authorization echoes into places that serve text to the dashboard.
        self.rate_limit_headers: dict[str, str] = dict(headers or {})


class OpenAICompatSidecarUnavailableError(OpenAICompatSidecarError):
    def __init__(self, message: str) -> None:
        super().__init__(503, message, body=None)


class OpenAICompatSidecarClient:
    def __init__(self, config: OpenAICompatSidecarConfig) -> None:
        self._config = config
        self._models_cache: list[SidecarModel] | None = None
        self._models_cache_fetched_at: float = 0.0

    @property
    def config(self) -> OpenAICompatSidecarConfig:
        return self._config

    @property
    def base_url(self) -> str:
        # Re-validated here, not merely at save time: a stored blob can predate
        # the validator or be edited out of band, and this property is the last
        # point before the bearer token is put on the wire.
        return normalize_openai_compat_base_url(self._config.base_url)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "codex-lb/openai-compat",
        }
        api_key = (self._config.api_key or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _timeout(self) -> aiohttp.ClientTimeout:
        return aiohttp.ClientTimeout(
            total=self._config.request_timeout_seconds,
            connect=self._config.connect_timeout_seconds,
            sock_connect=self._config.connect_timeout_seconds,
        )

    async def list_models(self) -> list[SidecarModel]:
        url = f"{self.base_url}/models"
        try:
            async with lease_http_session() as session:
                async with session.get(url, headers=self._headers(), timeout=self._timeout()) as resp:
                    data = await _read_response_json(resp)
                    if resp.status >= 400:
                        raise _error_from_status(resp.status, data)
        except OpenAICompatSidecarError:
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
            raise OpenAICompatSidecarUnavailableError(
                _transport_message(exc, f"fetch {self._config.name} models")
            ) from exc

        if not is_json_mapping(data):
            raise OpenAICompatSidecarError(
                502, f"Invalid response format from {self._config.name} models API", body=data
            )
        raw_models = data.get("data")
        if not isinstance(raw_models, list):
            raise OpenAICompatSidecarError(502, f"Missing 'data' key in {self._config.name} models response", body=data)

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
                    owned_by=owned_by if isinstance(owned_by, str) else "openai_compat",
                    raw=cast(Mapping[str, JsonValue], entry),
                    pricing=_parse_openai_compat_pricing(entry.get("pricing")),
                )
            )
        get_runtime_pricing_registry().update_models(
            ((model.id, model.pricing) for model in models),
            provider=self._config.provider_id,
        )
        return models

    async def list_models_cached(self) -> list[SidecarModel]:
        now = time.monotonic()
        ttl = self._config.models_cache_ttl_seconds
        if self._models_cache is not None and ttl > 0 and now - self._models_cache_fetched_at < ttl:
            return list(self._models_cache)
        try:
            models = await self.list_models()
        except OpenAICompatSidecarError:
            if self._models_cache is not None:
                logger.warning(
                    "using cached OpenAI-compat models after refresh failure endpoint_id=%s",
                    self._config.endpoint_id,
                    exc_info=True,
                )
                return list(self._models_cache)
            logger.warning(
                "OpenAI-compat models unavailable endpoint_id=%s",
                self._config.endpoint_id,
                exc_info=True,
            )
            return []
        self._models_cache = list(models)
        self._models_cache_fetched_at = now
        return models

    async def chat_completion(self, payload: Mapping[str, JsonValue]) -> JsonValue:
        url = f"{self.base_url}/chat/completions"
        try:
            async with lease_http_session() as session:
                async with session.post(
                    url,
                    headers=self._headers(),
                    json=dict(payload),
                    timeout=self._timeout(),
                ) as resp:
                    data = await _read_response_json(resp)
                    if resp.status >= 400:
                        raise _error_from_status(resp.status, data, getattr(resp, "headers", None))
                    return data
        except OpenAICompatSidecarError:
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
            raise OpenAICompatSidecarUnavailableError(_transport_message(exc, f"call {self._config.name}")) from exc

    @asynccontextmanager
    async def stream_chat_completion(self, payload: Mapping[str, JsonValue]) -> AsyncIterator[AsyncIterator[bytes]]:
        url = f"{self.base_url}/chat/completions"
        try:
            async with lease_http_session() as session:
                async with session.post(
                    url,
                    headers=self._headers(),
                    json=dict(payload),
                    timeout=self._timeout(),
                ) as resp:
                    if resp.status >= 400:
                        data = await _read_response_json(resp)
                        raise _error_from_status(resp.status, data)
                    yield resp.content.iter_chunked(8192)
        except OpenAICompatSidecarError:
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
            raise OpenAICompatSidecarUnavailableError(_transport_message(exc, f"stream {self._config.name}")) from exc


# Per-endpoint client cache. ``list_models_cached`` keeps its TTL state on the
# instance, so a client built inline per request could never hit that cache.
#
# Keyed by endpoint id because operators can keep several named endpoints at
# once. A settings change for one endpoint produces a different
# ``OpenAICompatSidecarConfig`` and replaces only that entry, dropping the
# previous credential and cached model list for that endpoint alone.
_cached_clients: dict[str, OpenAICompatSidecarClient] = {}
_cached_clients_lock = threading.Lock()


def get_openai_compat_sidecar_client(config: OpenAICompatSidecarConfig) -> OpenAICompatSidecarClient:
    """Return a client whose models cache survives across requests."""

    global _cached_clients
    with _cached_clients_lock:
        cached = _cached_clients.get(config.endpoint_id)
        if cached is not None and cached.config == config:
            return cached
        client = OpenAICompatSidecarClient(config)
        _cached_clients[config.endpoint_id] = client
        return client


def retain_openai_compat_sidecar_clients(endpoint_ids: Collection[str]) -> None:
    """Drop cached clients for endpoints that no longer exist.

    Replacing an endpoint's config already evicts its entry, but *deleting* one
    never produces a config again, so the cache kept the removed endpoint's
    client - and with it the decrypted API key - alive for the whole process
    lifetime. Reconciling against the current endpoint-id set every time the
    endpoint list is read bounds the cache by the configured endpoints and drops
    the credential when the operator removes it.

    Cheap enough for the hot path: a membership test over at most
    ``OPENAI_COMPAT_MAX_ENDPOINTS`` ids, mutating only when something is stale.
    """

    retained = set(endpoint_ids)
    with _cached_clients_lock:
        stale = [endpoint_id for endpoint_id in _cached_clients if endpoint_id not in retained]
        for endpoint_id in stale:
            del _cached_clients[endpoint_id]


def reset_openai_compat_sidecar_client_cache() -> None:
    """Drop cached clients (and the credentials they hold)."""

    global _cached_clients
    with _cached_clients_lock:
        _cached_clients = {}


def _parse_openai_compat_pricing(pricing: JsonValue) -> ModelPrice | None:
    if not is_json_mapping(pricing):
        return None
    input_per_1m = parse_sidecar_per_token_usd(pricing.get("prompt"))
    output_per_1m = parse_sidecar_per_token_usd(pricing.get("completion"))
    if input_per_1m is None or output_per_1m is None:
        return None
    cached_input_per_1m = parse_sidecar_per_token_usd(pricing.get("input_cache_read"))
    return ModelPrice(
        input_per_1m=input_per_1m,
        output_per_1m=output_per_1m,
        cached_input_per_1m=cached_input_per_1m,
    )


async def _read_response_json(resp: aiohttp.ClientResponse) -> JsonValue:
    text = await resp.text()
    if not text:
        return {}
    try:
        return cast(JsonValue, json.loads(text))
    except json.JSONDecodeError:
        return {"message": text}


def _error_from_status(
    status_code: int, body: JsonValue, headers: Mapping[str, str] | None = None
) -> OpenAICompatSidecarError:
    message = f"OpenAI-compat endpoint returned HTTP {status_code}"
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
    return OpenAICompatSidecarError(status_code, message, body=body, headers=_rate_limit_headers(headers))


def _rate_limit_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    """Copy out only the documented retry/limit headers, case-insensitively.

    An allowlist rather than a redaction pass: anything not named here simply
    never leaves the transport boundary.
    """

    if not headers:
        return {}
    captured: dict[str, str] = {}
    for key, value in headers.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        lowered = key.lower()
        if lowered in RATE_LIMIT_HEADERS:
            captured[lowered] = value[:_HEADER_VALUE_MAX_CHARS]
    return captured


def _transport_message(exc: BaseException, action: str) -> str:
    detail = str(exc) or exc.__class__.__name__
    return f"Failed to {action}: {detail}"
