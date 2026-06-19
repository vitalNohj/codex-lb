from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

import httpx
import ollama

from app.core.clients.claude_sidecar import SidecarModel, SidecarPrefix
from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping

logger = logging.getLogger(__name__)

_CURATED_CLOUD_MODELS = frozenset(
    {
        "deepseek-v3.1:671b-cloud",
        "gpt-oss:20b-cloud",
        "gpt-oss:120b-cloud",
        "kimi-k2:1t-cloud",
        "qwen3-coder:480b-cloud",
        "kimi-k2-thinking",
    }
)


@dataclass(frozen=True, slots=True)
class OllamaSidecarConfig:
    enabled: bool
    base_url: str
    api_key: str | None
    prefixes: tuple[SidecarPrefix, ...]
    full_models: tuple[str, ...]
    connect_timeout_seconds: float
    request_timeout_seconds: float
    models_cache_ttl_seconds: float


class OllamaSidecarError(Exception):
    def __init__(self, status_code: int, message: str, *, body: JsonValue | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.body = body


class OllamaSidecarUnavailableError(OllamaSidecarError):
    def __init__(self, message: str) -> None:
        super().__init__(503, message, body=None)


type AsyncClientFactory = Callable[..., Any]


class OllamaSidecarClient:
    def __init__(
        self,
        config: OllamaSidecarConfig,
        *,
        async_client_factory: AsyncClientFactory = ollama.AsyncClient,
    ) -> None:
        self._config = config
        self._async_client_factory = async_client_factory
        self._models_cache: list[SidecarModel] | None = None
        self._models_cache_fetched_at: float = 0.0

    @property
    def config(self) -> OllamaSidecarConfig:
        return self._config

    @property
    def base_url(self) -> str:
        return self._config.base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        api_key = (self._config.api_key or "").strip()
        if not api_key:
            return {}
        return {"Authorization": f"Bearer {api_key}"}

    def _client(self) -> Any:
        # ollama-python forwards extra kwargs to httpx.AsyncClient. This keeps
        # connect and total request timeouts separate while using the SDK for I/O.
        timeout = httpx.Timeout(
            timeout=self._config.request_timeout_seconds,
            connect=self._config.connect_timeout_seconds,
        )
        return self._async_client_factory(host=self.base_url, headers=self._headers(), timeout=timeout)

    async def list_models(self) -> list[SidecarModel]:
        try:
            response = await self._client().list()
        except ollama.ResponseError as exc:
            raise _error_from_response(exc) from exc
        except (ollama.RequestError, httpx.HTTPError, asyncio.TimeoutError, OSError) as exc:
            raise OllamaSidecarUnavailableError(_transport_message(exc, "fetch Ollama sidecar models")) from exc

        raw_models = _models_from_list_response(response)
        models: list[SidecarModel] = []
        seen: set[str] = set()
        for entry in raw_models:
            model_id = _model_id(entry)
            if model_id is None or not _is_cloud_model_id(model_id):
                continue
            key = model_id.lower()
            if key in seen:
                continue
            seen.add(key)
            models.append(
                SidecarModel(
                    id=model_id,
                    created=_created_at(entry),
                    owned_by="ollama",
                    raw=_raw_model(entry),
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
        except OllamaSidecarError:
            if self._models_cache is not None:
                logger.warning("using cached Ollama sidecar models after refresh failure", exc_info=True)
                return list(self._models_cache)
            logger.warning("Ollama sidecar models unavailable", exc_info=True)
            return []
        self._models_cache = list(models)
        self._models_cache_fetched_at = now
        return models

    async def chat_completion(self, payload: Mapping[str, JsonValue]) -> JsonValue:
        try:
            response = await self._client().chat(**_chat_kwargs(payload, stream=False))
        except ollama.ResponseError as exc:
            raise _error_from_response(exc) from exc
        except (ollama.RequestError, httpx.HTTPError, asyncio.TimeoutError, OSError) as exc:
            raise OllamaSidecarUnavailableError(_transport_message(exc, "call Ollama sidecar")) from exc
        return _normalize_sdk_value(response)

    async def stream_chat_completion(self, payload: Mapping[str, JsonValue]) -> AsyncIterator[JsonValue]:
        try:
            stream = await self._client().chat(**_chat_kwargs(payload, stream=True))
            async for chunk in stream:
                yield _normalize_sdk_value(chunk)
        except ollama.ResponseError as exc:
            raise _error_from_response(exc) from exc
        except (ollama.RequestError, httpx.HTTPError, asyncio.TimeoutError, OSError) as exc:
            raise OllamaSidecarUnavailableError(_transport_message(exc, "stream Ollama sidecar")) from exc


def is_ollama_cloud_model_id(model_id: str) -> bool:
    return _is_cloud_model_id(model_id)


def _is_cloud_model_id(model_id: str) -> bool:
    normalized = model_id.strip().lower()
    return normalized.endswith("-cloud") or ":cloud" in normalized or normalized in _CURATED_CLOUD_MODELS


def _models_from_list_response(response: object) -> list[object]:
    if is_json_mapping(response):
        raw_models = response.get("models")
        return raw_models if isinstance(raw_models, list) else []
    raw_models = getattr(response, "models", None)
    return raw_models if isinstance(raw_models, list) else []


def _model_id(entry: object) -> str | None:
    value: object
    if is_json_mapping(entry):
        value = entry.get("model") or entry.get("name")
    else:
        value = getattr(entry, "model", None) or getattr(entry, "name", None)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _created_at(entry: object) -> int | None:
    value: object
    if is_json_mapping(entry):
        value = entry.get("modified_at") or entry.get("created")
    else:
        value = getattr(entry, "modified_at", None) or getattr(entry, "created", None)
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, datetime):
        return int(value.timestamp())
    return None


def _raw_model(entry: object) -> Mapping[str, JsonValue] | None:
    normalized = _normalize_sdk_value(entry)
    if is_json_mapping(normalized):
        return cast(Mapping[str, JsonValue], normalized)
    return None


def _chat_kwargs(payload: Mapping[str, JsonValue], *, stream: bool) -> dict[str, object]:
    model = payload.get("model")
    kwargs: dict[str, object] = {"model": model if isinstance(model, str) else "", "stream": stream}
    messages = payload.get("messages")
    if isinstance(messages, list):
        kwargs["messages"] = messages
    tools = payload.get("tools")
    if isinstance(tools, list):
        kwargs["tools"] = tools
    response_format = payload.get("format")
    if isinstance(response_format, str) or is_json_mapping(response_format):
        kwargs["format"] = response_format
    options = payload.get("options")
    if is_json_mapping(options):
        kwargs["options"] = options
    think = payload.get("think")
    if isinstance(think, bool | str):
        kwargs["think"] = think
    return kwargs


def _normalize_sdk_value(value: object) -> JsonValue:
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json", exclude_none=True)
        return cast(JsonValue, dumped)
    return cast(JsonValue, value)


def _error_from_response(exc: ollama.ResponseError) -> OllamaSidecarError:
    status_code = int(getattr(exc, "status_code", -1) or 502)
    if status_code < 100:
        status_code = 502
    message = str(exc.error or exc)
    return OllamaSidecarError(status_code, message, body={"message": message})


def _transport_message(exc: BaseException, action: str) -> str:
    detail = str(exc) or exc.__class__.__name__
    return f"Failed to {action}: {detail}"
