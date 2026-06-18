from __future__ import annotations

import asyncio
import json
import logging
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
class OpenRouterSidecarConfig:
    enabled: bool
    base_url: str
    api_key: str | None
    prefixes: tuple[SidecarPrefix, ...]
    connect_timeout_seconds: float
    request_timeout_seconds: float
    models_cache_ttl_seconds: float
    full_models: tuple[str, ...] = ()


class OpenRouterSidecarError(Exception):
    def __init__(self, status_code: int, message: str, *, body: JsonValue | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.body = body


class OpenRouterSidecarUnavailableError(OpenRouterSidecarError):
    def __init__(self, message: str) -> None:
        super().__init__(503, message, body=None)


class OpenRouterSidecarClient:
    def __init__(self, config: OpenRouterSidecarConfig) -> None:
        self._config = config
        self._models_cache: list[SidecarModel] | None = None
        self._models_cache_fetched_at: float = 0.0

    @property
    def config(self) -> OpenRouterSidecarConfig:
        return self._config

    @property
    def base_url(self) -> str:
        return self._config.base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "codex-lb/openrouter-sidecar",
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
        except OpenRouterSidecarError:
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
            raise OpenRouterSidecarUnavailableError(
                _transport_message(exc, "fetch OpenRouter sidecar models")
            ) from exc

        if not is_json_mapping(data):
            raise OpenRouterSidecarError(502, "Invalid response format from OpenRouter models API", body=data)
        raw_models = data.get("data")
        if not isinstance(raw_models, list):
            raise OpenRouterSidecarError(502, "Missing 'data' key in OpenRouter models response", body=data)

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
                    owned_by=owned_by if isinstance(owned_by, str) else "openrouter",
                    raw=cast(Mapping[str, JsonValue], entry),
                    pricing=_parse_openrouter_pricing(entry.get("pricing")),
                )
            )
        get_runtime_pricing_registry().update_models((model.id, model.pricing) for model in models)
        return models

    async def list_models_cached(self) -> list[SidecarModel]:
        now = time.monotonic()
        ttl = self._config.models_cache_ttl_seconds
        if self._models_cache is not None and ttl > 0 and now - self._models_cache_fetched_at < ttl:
            return list(self._models_cache)
        try:
            models = await self.list_models()
        except OpenRouterSidecarError:
            if self._models_cache is not None:
                logger.warning("using cached OpenRouter sidecar models after refresh failure", exc_info=True)
                return list(self._models_cache)
            logger.warning("OpenRouter sidecar models unavailable", exc_info=True)
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
        except OpenRouterSidecarError:
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
            raise OpenRouterSidecarUnavailableError(_transport_message(exc, "call OpenRouter sidecar")) from exc

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
        except OpenRouterSidecarError:
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
            raise OpenRouterSidecarUnavailableError(_transport_message(exc, "stream OpenRouter sidecar")) from exc


_PER_TOKEN_TO_PER_1M = 1_000_000.0


def _parse_per_token_usd(value: JsonValue) -> float | None:
    """Parse an OpenRouter per-token USD price (decimal string) to per-1M tokens."""
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


def _parse_openrouter_pricing(pricing: JsonValue) -> ModelPrice | None:
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


def _error_from_status(status_code: int, body: JsonValue) -> OpenRouterSidecarError:
    message = f"OpenRouter sidecar returned HTTP {status_code}"
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
    return OpenRouterSidecarError(status_code, message, body=body)


def _transport_message(exc: BaseException, action: str) -> str:
    detail = str(exc) or exc.__class__.__name__
    return f"Failed to {action}: {detail}"
