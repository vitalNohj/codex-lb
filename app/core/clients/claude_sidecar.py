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

from app.core.clients.http import lease_http_session
from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ClaudeSidecarConfig:
    enabled: bool
    base_url: str
    api_key: str | None
    model_prefixes: tuple[str, ...]
    connect_timeout_seconds: float
    request_timeout_seconds: float
    models_cache_ttl_seconds: float
    management_key: str | None = None


@dataclass(frozen=True, slots=True)
class SidecarModel:
    id: str
    created: int | None = None
    owned_by: str | None = None
    raw: Mapping[str, JsonValue] | None = None


class ClaudeSidecarError(Exception):
    def __init__(self, status_code: int, message: str, *, body: JsonValue | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.body = body


class ClaudeSidecarUnavailableError(ClaudeSidecarError):
    def __init__(self, message: str) -> None:
        super().__init__(503, message, body=None)


class ClaudeSidecarClient:
    def __init__(self, config: ClaudeSidecarConfig) -> None:
        self._config = config
        self._models_cache: list[SidecarModel] | None = None
        self._models_cache_fetched_at: float = 0.0

    @property
    def config(self) -> ClaudeSidecarConfig:
        return self._config

    @property
    def base_url(self) -> str:
        return self._config.base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "codex-lb/claude-sidecar",
        }
        api_key = (self._config.api_key or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _management_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "codex-lb/claude-sidecar-management",
        }
        management_key = (self._config.management_key or "").strip()
        if management_key:
            headers["Authorization"] = f"Bearer {management_key}"
        return headers

    def _timeout(self) -> aiohttp.ClientTimeout:
        return aiohttp.ClientTimeout(
            total=self._config.request_timeout_seconds,
            connect=self._config.connect_timeout_seconds,
            sock_connect=self._config.connect_timeout_seconds,
        )

    async def list_models(self) -> list[SidecarModel]:
        url = f"{self.base_url}/v1/models"
        try:
            async with lease_http_session() as session:
                async with session.get(url, headers=self._headers(), timeout=self._timeout()) as resp:
                    data = await _read_response_json(resp)
                    if resp.status >= 400:
                        raise _error_from_status(resp.status, data)
        except ClaudeSidecarError:
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
            raise ClaudeSidecarUnavailableError(_transport_message(exc, "fetch Claude sidecar models")) from exc

        if not is_json_mapping(data):
            raise ClaudeSidecarError(502, "Invalid response format from Claude sidecar models API", body=data)
        raw_models = data.get("data")
        if not isinstance(raw_models, list):
            raise ClaudeSidecarError(502, "Missing 'data' key in Claude sidecar models response", body=data)

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
                    owned_by=owned_by if isinstance(owned_by, str) else None,
                    raw=cast(Mapping[str, JsonValue], entry),
                )
            )
        return models

    async def list_auth_files(self) -> list[Mapping[str, JsonValue]]:
        url = f"{self.base_url}/v0/management/auth-files"
        try:
            async with lease_http_session() as session:
                async with session.get(url, headers=self._management_headers(), timeout=self._timeout()) as resp:
                    data = await _read_response_json(resp)
                    if resp.status >= 400:
                        raise _error_from_status(resp.status, data)
        except ClaudeSidecarError:
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
            raise ClaudeSidecarUnavailableError(_transport_message(exc, "fetch Claude sidecar auth files")) from exc

        if not is_json_mapping(data):
            raise ClaudeSidecarError(502, "Invalid response format from Claude sidecar management API", body=data)
        raw_files = data.get("files")
        if not isinstance(raw_files, list):
            raise ClaudeSidecarError(502, "Missing 'files' key in Claude sidecar management response", body=data)
        files: list[Mapping[str, JsonValue]] = []
        for entry in raw_files:
            if is_json_mapping(entry):
                files.append(cast(Mapping[str, JsonValue], entry))
        return files

    async def list_models_cached(self) -> list[SidecarModel]:
        now = time.monotonic()
        ttl = self._config.models_cache_ttl_seconds
        if self._models_cache is not None and ttl > 0 and now - self._models_cache_fetched_at < ttl:
            return list(self._models_cache)
        try:
            models = await self.list_models()
        except ClaudeSidecarError:
            if self._models_cache is not None:
                logger.warning("using cached Claude sidecar models after refresh failure", exc_info=True)
                return list(self._models_cache)
            logger.warning("Claude sidecar models unavailable", exc_info=True)
            return []
        self._models_cache = list(models)
        self._models_cache_fetched_at = now
        return models

    async def chat_completion(self, payload: Mapping[str, JsonValue]) -> JsonValue:
        url = f"{self.base_url}/v1/chat/completions"
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
        except ClaudeSidecarError:
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
            raise ClaudeSidecarUnavailableError(_transport_message(exc, "call Claude sidecar")) from exc

    @asynccontextmanager
    async def stream_chat_completion(self, payload: Mapping[str, JsonValue]) -> AsyncIterator[AsyncIterator[bytes]]:
        url = f"{self.base_url}/v1/chat/completions"
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
        except ClaudeSidecarError:
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
            raise ClaudeSidecarUnavailableError(_transport_message(exc, "stream Claude sidecar")) from exc


async def _read_response_json(resp: aiohttp.ClientResponse) -> JsonValue:
    text = await resp.text()
    if not text:
        return {}
    try:
        return cast(JsonValue, json.loads(text))
    except json.JSONDecodeError:
        return {"message": text}


def _error_from_status(status_code: int, body: JsonValue) -> ClaudeSidecarError:
    message = f"Claude sidecar returned HTTP {status_code}"
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
    return ClaudeSidecarError(status_code, message, body=body)


def _transport_message(exc: BaseException, action: str) -> str:
    detail = str(exc) or exc.__class__.__name__
    return f"Failed to {action}: {detail}"
