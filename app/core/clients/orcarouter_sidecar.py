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

from app.core.clients.claude_sidecar import SidecarModel, SidecarPrefix
from app.core.clients.http import lease_http_session
from app.core.types import JsonValue
from app.core.usage.pricing import ModelPrice
from app.core.usage.runtime_pricing import get_runtime_pricing_registry
from app.core.utils.json_guards import is_json_mapping

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OrcaRouterSidecarConfig:
    enabled: bool
    base_url: str
    api_key: str | None
    prefixes: tuple[SidecarPrefix, ...]
    connect_timeout_seconds: float
    request_timeout_seconds: float
    models_cache_ttl_seconds: float
    full_models: tuple[str, ...] = ()
    default_reasoning_effort: str | None = None


class OrcaRouterSidecarError(Exception):
    def __init__(self, status_code: int, message: str, *, body: JsonValue | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.body = body


class OrcaRouterSidecarUnavailableError(OrcaRouterSidecarError):
    def __init__(self, message: str) -> None:
        super().__init__(503, message, body=None)


_INCLUDE_COST_HEADER = "X-OrcaRouter-Include-Cost"

# Runtime pricing key space for this integration. OrcaRouter and OpenRouter both
# list ids such as ``deepseek/deepseek-chat`` at their own list prices, so a
# shared unqualified key space would let whichever refresh ran last define the
# reference cost for the other provider's requests.
ORCAROUTER_PRICING_PROVIDER = "orcarouter"


class OrcaRouterSidecarClient:
    def __init__(self, config: OrcaRouterSidecarConfig) -> None:
        self._config = config
        self._models_cache: list[SidecarModel] | None = None
        self._models_cache_fetched_at: float = 0.0

    @property
    def config(self) -> OrcaRouterSidecarConfig:
        return self._config

    @property
    def base_url(self) -> str:
        return self._config.base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "codex-lb/orcarouter-sidecar",
            "HTTP-Referer": "https://github.com/vitalNohj/codex-lb",
            "X-Title": "codex-lb",
            # Opt in to the billed figure on the response's usage object. Without
            # this header OrcaRouter omits ``usage.cost_usd`` entirely, and its
            # billed amount is not reproducible client-side (tiered pricing,
            # peak multipliers, cache ratios, minimum-quota rounding).
            # docs.orcarouter.ai/operations/per-request-cost
            _INCLUDE_COST_HEADER: "true",
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
        except OrcaRouterSidecarError:
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
            raise OrcaRouterSidecarUnavailableError(
                _transport_message(exc, "fetch OrcaRouter sidecar models")
            ) from exc

        if not is_json_mapping(data):
            raise OrcaRouterSidecarError(502, "Invalid response format from OrcaRouter models API", body=data)
        raw_models = data.get("data")
        if not isinstance(raw_models, list):
            raise OrcaRouterSidecarError(502, "Missing 'data' key in OrcaRouter models response", body=data)

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
                    owned_by=owned_by if isinstance(owned_by, str) else "orcarouter",
                    raw=cast(Mapping[str, JsonValue], entry),
                    pricing=_parse_orcarouter_pricing(entry.get("pricing")),
                )
            )
        get_runtime_pricing_registry().update_models(
            ((model.id, model.pricing) for model in models),
            provider=ORCAROUTER_PRICING_PROVIDER,
        )
        return models

    async def list_models_cached(self) -> list[SidecarModel]:
        now = time.monotonic()
        ttl = self._config.models_cache_ttl_seconds
        if self._models_cache is not None and ttl > 0 and now - self._models_cache_fetched_at < ttl:
            return list(self._models_cache)
        try:
            models = await self.list_models()
        except OrcaRouterSidecarError:
            if self._models_cache is not None:
                logger.warning("using cached OrcaRouter sidecar models after refresh failure", exc_info=True)
                return list(self._models_cache)
            logger.warning("OrcaRouter sidecar models unavailable", exc_info=True)
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
                        raise _error_from_status(resp.status, data)
                    return data
        except OrcaRouterSidecarError:
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
            raise OrcaRouterSidecarUnavailableError(_transport_message(exc, "call OrcaRouter sidecar")) from exc

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
        except OrcaRouterSidecarError:
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
            raise OrcaRouterSidecarUnavailableError(_transport_message(exc, "stream OrcaRouter sidecar")) from exc


# Single-entry, config-keyed client cache. ``list_models_cached`` keeps its TTL
# state on the instance, so a client built inline per request could never hit
# that cache and every ``GET /v1/models`` paid another upstream round trip.
#
# Holding exactly one entry - rather than a dict keyed by config - is what makes
# a settings change safe: any change to the base URL, API key, prefixes, or TTL
# produces a different ``OrcaRouterSidecarConfig``, which evicts the previous
# client together with its cached models and its copy of the old credential.
_cached_client: OrcaRouterSidecarClient | None = None
_cached_client_lock = threading.Lock()


def get_orcarouter_sidecar_client(config: OrcaRouterSidecarConfig) -> OrcaRouterSidecarClient:
    """Return a client whose models cache survives across requests."""

    global _cached_client
    with _cached_client_lock:
        cached = _cached_client
        if cached is not None and cached.config == config:
            return cached
        client = OrcaRouterSidecarClient(config)
        _cached_client = client
        return client


def reset_orcarouter_sidecar_client_cache() -> None:
    """Drop the cached client (and the credential it holds)."""

    global _cached_client
    with _cached_client_lock:
        _cached_client = None


_REDACTION = "[redacted]"
# Token charset mirrors app/core/runtime_logging.py so the closing quote/brace of
# an echoed header survives while the credential does not.
_BEARER_TOKEN_RE = re.compile(r"(?i)(bearer[\s:=]+)[A-Za-z0-9._~+/=-]+")
# OrcaRouter keys carry an ``sk-orca-`` prefix and can be echoed bare, with no
# ``Bearer`` in front ("Invalid API key: sk-orca-...").
_ORCAROUTER_KEY_RE = re.compile(r"(?i)sk-orca-[A-Za-z0-9._~+/=-]+")


def sanitize_orcarouter_message(message: str, *, api_key: str | None = None) -> str:
    """Strip the OrcaRouter credential out of an operator- or client-visible string.

    Every path that surfaces upstream text shares this one implementation: the
    health check persists it to ``orcarouter_sidecar_last_health_message``, and
    chat dispatch persists it to ``request_logs.error_message`` (rendered by the
    dashboard request drawer) and hands it back to the calling API key. An
    upstream that echoes the Authorization header must not leak the key on any of
    them. The configured key is removed verbatim first - that is exact rather
    than pattern-guessed - and the ``Bearer``/``sk-orca-`` patterns then cover
    keys that are no longer the configured one.
    """

    sanitized = message
    configured_key = (api_key or "").strip()
    if configured_key:
        sanitized = sanitized.replace(configured_key, _REDACTION)
    sanitized = _BEARER_TOKEN_RE.sub(rf"\g<1>{_REDACTION}", sanitized)
    return _ORCAROUTER_KEY_RE.sub(_REDACTION, sanitized)


def sanitize_orcarouter_error_body(body: JsonValue | None, *, api_key: str | None = None) -> JsonValue | None:
    """Sanitize every string inside an upstream error body.

    ``client_facing_sidecar_error`` relays the upstream body verbatim to the
    calling API key for non-401/403 statuses, so the credential has to be removed
    from the nested payload too, not only from the flattened message.
    """

    if isinstance(body, str):
        return sanitize_orcarouter_message(body, api_key=api_key)
    if isinstance(body, list):
        return [sanitize_orcarouter_error_body(entry, api_key=api_key) for entry in body]
    if is_json_mapping(body):
        return {key: sanitize_orcarouter_error_body(value, api_key=api_key) for key, value in body.items()}
    return body


_PER_TOKEN_TO_PER_1M = 1_000_000.0


def _parse_per_token_usd(value: JsonValue) -> float | None:
    """Parse an OrcaRouter per-token USD price (decimal string) to per-1M tokens."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        per_token = float(value)
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            per_token = float(stripped)
        except ValueError:
            return None
    else:
        return None
    if per_token < 0:
        return None
    return per_token * _PER_TOKEN_TO_PER_1M


def _parse_orcarouter_pricing(pricing: JsonValue) -> ModelPrice | None:
    if not is_json_mapping(pricing):
        return None
    input_per_1m = _parse_per_token_usd(pricing.get("prompt"))
    output_per_1m = _parse_per_token_usd(pricing.get("completion"))
    if input_per_1m is None or output_per_1m is None:
        return None
    cached_input_per_1m = _parse_per_token_usd(pricing.get("input_cache_read"))
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


def _error_from_status(status_code: int, body: JsonValue) -> OrcaRouterSidecarError:
    message = f"OrcaRouter sidecar returned HTTP {status_code}"
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
    return OrcaRouterSidecarError(status_code, message, body=body)


def _transport_message(exc: BaseException, action: str) -> str:
    detail = str(exc) or exc.__class__.__name__
    return f"Failed to {action}: {detail}"
