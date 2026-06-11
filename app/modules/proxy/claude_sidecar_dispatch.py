from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import cast

from fastapi import Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.clients.claude_sidecar import (
    ClaudeSidecarClient,
    ClaudeSidecarConfig,
    ClaudeSidecarError,
    ClaudeSidecarUnavailableError,
)
from app.core.config.settings_cache import get_settings_cache
from app.core.crypto import TokenEncryptor
from app.core.errors import OpenAIErrorEnvelope, openai_error
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.core.types import JsonObject, JsonValue
from app.core.utils.json_guards import is_json_mapping
from app.core.utils.request_id import get_request_id
from app.core.utils.sse import inject_sse_keepalives
from app.db.models import DashboardSettings
from app.db.session import get_background_session
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyData, ApiKeysService, ApiKeyUsageReservationData
from app.modules.request_logs.repository import RequestLogsRepository

logger = logging.getLogger(__name__)

_SIDECAR_TOOL_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
_SIDECAR_TOOL_ID_INVALID_CHAR = re.compile(r"[^a-zA-Z0-9_-]")
_SIDECAR_TOOL_CALL_ID_FIELDS = ("tool_call_id", "toolCallId", "call_id")
_SIDECAR_TOOL_CONTENT_CALL_ID_TYPES = frozenset(
    {"function_call", "custom_tool_call", "function_call_output", "custom_tool_call_output"}
)


@dataclass(frozen=True, slots=True)
class SidecarUsage:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0


def is_sidecar_model(model: str, config: ClaudeSidecarConfig) -> bool:
    if not config.enabled:
        return False
    return sidecar_prefix_match(model, config)


def sidecar_prefix_match(model: str, config: ClaudeSidecarConfig) -> bool:
    return _matching_sidecar_prefix(model, config) is not None


def sidecar_wire_model(model: str, config: ClaudeSidecarConfig) -> str:
    normalized_model = model.strip()
    prefix = _matching_sidecar_prefix(normalized_model, config)
    if prefix is None or not _is_custom_alias_prefix(prefix):
        return normalized_model
    return normalized_model[len(prefix) :].strip() or normalized_model


def _matching_sidecar_prefix(model: str, config: ClaudeSidecarConfig) -> str | None:
    normalized = model.strip().lower()
    for prefix in config.model_prefixes:
        for candidate in _sidecar_prefix_variants(prefix):
            if normalized.startswith(candidate):
                return candidate
    return None


def _sidecar_prefix_variants(prefix: str) -> tuple[str, ...]:
    normalized = prefix.strip().lower()
    if not normalized:
        return ()
    if normalized.endswith("-"):
        return (normalized, f"{normalized[:-1]}_")
    if normalized.endswith("_"):
        return (normalized, f"{normalized[:-1]}-")
    return (normalized,)


def _is_custom_alias_prefix(prefix: str) -> bool:
    return prefix.endswith(("-", "_"))


async def load_sidecar_config() -> ClaudeSidecarConfig | None:
    try:
        dashboard_settings = await get_settings_cache().get()
    except Exception:
        logger.warning("failed to load dashboard settings for Claude sidecar", exc_info=True)
        return None
    return sidecar_config_from_settings(dashboard_settings)


def sidecar_config_from_settings(settings: DashboardSettings) -> ClaudeSidecarConfig:
    api_key = _decrypt_sidecar_secret(settings.claude_sidecar_api_key_encrypted, label="API key")
    management_key = _decrypt_sidecar_secret(
        settings.claude_sidecar_management_key_encrypted, label="management key"
    )
    return ClaudeSidecarConfig(
        enabled=bool(settings.claude_sidecar_enabled),
        base_url=settings.claude_sidecar_base_url.rstrip("/"),
        api_key=api_key,
        model_prefixes=tuple(_parse_sidecar_prefixes(settings.claude_sidecar_model_prefixes_json)),
        connect_timeout_seconds=settings.claude_sidecar_connect_timeout_seconds,
        request_timeout_seconds=settings.claude_sidecar_request_timeout_seconds,
        models_cache_ttl_seconds=settings.claude_sidecar_models_cache_ttl_seconds,
        management_key=management_key,
    )


def _decrypt_sidecar_secret(encrypted: bytes | None, *, label: str) -> str | None:
    if not encrypted:
        return None
    try:
        return TokenEncryptor().decrypt(encrypted)
    except Exception:
        logger.warning("failed to decrypt Claude sidecar %s", label, exc_info=True)
        return None


def _parse_sidecar_prefixes(raw: str | None) -> list[str]:
    if not raw:
        return ["claude"]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return ["claude"]
    if not isinstance(parsed, list):
        return ["claude"]
    prefixes = [entry.strip().lower() for entry in parsed if isinstance(entry, str) and entry.strip()]
    return prefixes or ["claude"]


def sanitize_sidecar_chat_tool_ids(body: dict[str, JsonValue]) -> None:
    cache: dict[str, str] = {}
    used: set[str] = set()
    messages = body.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if is_json_mapping(message):
                _sanitize_sidecar_message_tool_ids(cast(dict[str, JsonValue], message), cache=cache, used=used)
    input_items = body.get("input")
    if isinstance(input_items, list):
        for item in input_items:
            if is_json_mapping(item):
                _sanitize_sidecar_input_item_tool_ids(cast(dict[str, JsonValue], item), cache=cache, used=used)


def build_sidecar_chat_payload(
    payload: ChatCompletionsRequest,
    effective_model: str,
    config: ClaudeSidecarConfig,
) -> dict[str, JsonValue]:
    body = cast(dict[str, JsonValue], payload.model_dump(mode="json", exclude_none=True))
    body["model"] = sidecar_wire_model(effective_model, config)
    sanitize_sidecar_chat_tool_ids(body)
    return body


def _sanitize_sidecar_tool_id(tool_id: str, *, cache: dict[str, str], used: set[str]) -> str:
    if _SIDECAR_TOOL_ID_PATTERN.fullmatch(tool_id):
        used.add(tool_id)
        return tool_id
    cached = cache.get(tool_id)
    if cached is not None:
        return cached
    sanitized = _SIDECAR_TOOL_ID_INVALID_CHAR.sub("_", tool_id).strip("_") or "tool_id"
    if sanitized in used:
        base = sanitized
        suffix = 1
        while f"{base}_{suffix}" in used:
            suffix += 1
        sanitized = f"{base}_{suffix}"
    cache[tool_id] = sanitized
    used.add(sanitized)
    return sanitized


def _rewrite_sidecar_tool_id_field(
    container: dict[str, JsonValue],
    field: str,
    *,
    cache: dict[str, str],
    used: set[str],
) -> None:
    value = container.get(field)
    if isinstance(value, str) and value:
        container[field] = _sanitize_sidecar_tool_id(value, cache=cache, used=used)


def _sanitize_sidecar_content_tool_ids(
    content: list[JsonValue],
    *,
    cache: dict[str, str],
    used: set[str],
) -> None:
    for part in content:
        if not is_json_mapping(part):
            continue
        part_dict = cast(dict[str, JsonValue], part)
        part_type = part_dict.get("type")
        if part_type == "tool_use":
            _rewrite_sidecar_tool_id_field(part_dict, "id", cache=cache, used=used)
        elif part_type == "tool_result":
            _rewrite_sidecar_tool_id_field(part_dict, "tool_use_id", cache=cache, used=used)
        elif isinstance(part_type, str) and part_type in _SIDECAR_TOOL_CONTENT_CALL_ID_TYPES:
            _rewrite_sidecar_tool_id_field(part_dict, "call_id", cache=cache, used=used)


def _sanitize_sidecar_message_tool_ids(
    message: dict[str, JsonValue],
    *,
    cache: dict[str, str],
    used: set[str],
) -> None:
    content = message.get("content")
    if isinstance(content, list):
        _sanitize_sidecar_content_tool_ids(content, cache=cache, used=used)

    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for tool_call in tool_calls:
            if is_json_mapping(tool_call):
                _rewrite_sidecar_tool_id_field(
                    cast(dict[str, JsonValue], tool_call),
                    "id",
                    cache=cache,
                    used=used,
                )

    if message.get("role") == "tool":
        for field in _SIDECAR_TOOL_CALL_ID_FIELDS:
            _rewrite_sidecar_tool_id_field(message, field, cache=cache, used=used)

    function_call = message.get("function_call")
    if is_json_mapping(function_call):
        _rewrite_sidecar_tool_id_field(cast(dict[str, JsonValue], function_call), "id", cache=cache, used=used)


def _sanitize_sidecar_input_item_tool_ids(
    item: dict[str, JsonValue],
    *,
    cache: dict[str, str],
    used: set[str],
) -> None:
    item_type = item.get("type")
    if isinstance(item_type, str) and item_type in _SIDECAR_TOOL_CONTENT_CALL_ID_TYPES:
        _rewrite_sidecar_tool_id_field(item, "call_id", cache=cache, used=used)
    content = item.get("content")
    if isinstance(content, list):
        _sanitize_sidecar_content_tool_ids(content, cache=cache, used=used)


def ensure_stream_usage_requested(payload: dict[str, JsonValue]) -> None:
    raw_options = payload.get("stream_options")
    if is_json_mapping(raw_options):
        options: dict[str, JsonValue] = dict(raw_options)
    else:
        options = {}
    options["include_usage"] = True
    payload["stream_options"] = options


async def proxy_chat_to_sidecar(
    request: Request,
    payload: ChatCompletionsRequest,
    *,
    effective_model: str,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    rate_limit_headers: Mapping[str, str],
    sse_keepalive_interval_seconds: float,
    client: ClaudeSidecarClient,
) -> Response:
    body = build_sidecar_chat_payload(payload, effective_model, client.config)
    requested_at = time.monotonic()
    if payload.stream:
        ensure_stream_usage_requested(body)
        return StreamingResponse(
            inject_sse_keepalives(
                _sidecar_stream_iterator(
                    body,
                    api_key=api_key,
                    reservation=reservation,
                    model=effective_model,
                    started_at=requested_at,
                    client=client,
                ),
                sse_keepalive_interval_seconds,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", **dict(rate_limit_headers)},
        )

    try:
        response_body = await client.chat_completion(body)
    except ClaudeSidecarUnavailableError:
        await _release_sidecar_reservation(reservation, api_key=api_key)
        await _log_sidecar_request(
            api_key=api_key,
            model=effective_model,
            started_at=requested_at,
            status="error",
            error_code="claude_sidecar_unavailable",
            error_message="Claude sidecar unavailable",
        )
        return JSONResponse(
            status_code=503,
            content=openai_error(
                "claude_sidecar_unavailable",
                "Claude sidecar unavailable",
                error_type="upstream_error",
            ),
            headers=dict(rate_limit_headers),
        )
    except ClaudeSidecarError as exc:
        await _release_sidecar_reservation(reservation, api_key=api_key)
        await _log_sidecar_request(
            api_key=api_key,
            model=effective_model,
            started_at=requested_at,
            status="error",
            error_code="claude_sidecar_error",
            error_message=exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_openai_error_content(exc),
            headers=dict(rate_limit_headers),
        )

    usage = extract_usage(response_body)
    await _finalize_or_release_sidecar_reservation(
        reservation,
        api_key=api_key,
        model=effective_model,
        usage=usage,
    )
    await _log_sidecar_request(
        api_key=api_key,
        model=effective_model,
        started_at=requested_at,
        status="success",
        usage=usage,
    )
    return JSONResponse(content=response_body, status_code=200, headers=dict(rate_limit_headers))


async def _sidecar_stream_iterator(
    payload: Mapping[str, JsonValue],
    *,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    model: str,
    started_at: float,
    client: ClaudeSidecarClient,
) -> AsyncIterator[bytes]:
    usage: SidecarUsage | None = None
    completed = False
    settled = False
    try:
        async with client.stream_chat_completion(payload) as chunks:
            decoder = _SseUsageDecoder()
            async for raw_chunk in chunks:
                for event in decoder.feed(raw_chunk.decode("utf-8", errors="ignore")):
                    if event == "[DONE]":
                        completed = True
                        continue
                    event_usage = extract_usage(event)
                    if event_usage is not None:
                        usage = event_usage
                yield raw_chunk
            for event in decoder.flush():
                if event == "[DONE]":
                    completed = True
                    continue
                event_usage = extract_usage(event)
                if event_usage is not None:
                    usage = event_usage
    except ClaudeSidecarUnavailableError:
        await _release_sidecar_reservation(reservation, api_key=api_key)
        await _log_sidecar_request(
            api_key=api_key,
            model=model,
            started_at=started_at,
            status="error",
            error_code="claude_sidecar_unavailable",
            error_message="Claude sidecar unavailable",
        )
        settled = True
        yield _error_sse(
            openai_error(
                "claude_sidecar_unavailable",
                "Claude sidecar unavailable",
                error_type="upstream_error",
            )
        )
        yield b"data: [DONE]\n\n"
    except ClaudeSidecarError as exc:
        await _release_sidecar_reservation(reservation, api_key=api_key)
        await _log_sidecar_request(
            api_key=api_key,
            model=model,
            started_at=started_at,
            status="error",
            error_code="claude_sidecar_error",
            error_message=exc.message,
        )
        settled = True
        yield _error_sse(_openai_error_content(exc))
        yield b"data: [DONE]\n\n"
    except BaseException as exc:
        await _release_sidecar_reservation(reservation, api_key=api_key)
        await _log_sidecar_request(
            api_key=api_key,
            model=model,
            started_at=started_at,
            status="error",
            error_code="claude_sidecar_stream_interrupted",
            error_message=str(exc) or exc.__class__.__name__,
        )
        settled = True
        raise
    finally:
        if not settled:
            usage_to_settle = usage if completed else None
            await _finalize_or_release_sidecar_reservation(
                reservation,
                api_key=api_key,
                model=model,
                usage=usage_to_settle,
            )
            await _log_sidecar_request(
                api_key=api_key,
                model=model,
                started_at=started_at,
                status="success" if completed else "error",
                error_code=None if completed else "claude_sidecar_stream_incomplete",
                usage=usage_to_settle,
            )


def extract_usage(payload: JsonValue) -> SidecarUsage | None:
    if not is_json_mapping(payload):
        return None
    usage = payload.get("usage")
    if not is_json_mapping(usage):
        return None

    input_tokens = _int_field(usage, "prompt_tokens")
    if input_tokens is None:
        input_tokens = _int_field(usage, "input_tokens")
    output_tokens = _int_field(usage, "completion_tokens")
    if output_tokens is None:
        output_tokens = _int_field(usage, "output_tokens")
    if input_tokens is None or output_tokens is None:
        return None

    cached_tokens = 0
    prompt_details = usage.get("prompt_tokens_details")
    if is_json_mapping(prompt_details):
        cached_tokens = _int_field(prompt_details, "cached_tokens") or 0
    input_details = usage.get("input_tokens_details")
    if is_json_mapping(input_details):
        cached_tokens = _int_field(input_details, "cached_tokens") or cached_tokens
    return SidecarUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_tokens,
    )


class _SseUsageDecoder:
    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, chunk: str) -> list[JsonObject | str]:
        self._buffer += chunk
        return self._drain_complete_events()

    def flush(self) -> list[JsonObject | str]:
        if not self._buffer:
            return []
        pending = self._buffer
        self._buffer = ""
        event = _parse_sse_event(pending)
        return [event] if event is not None else []

    def _drain_complete_events(self) -> list[JsonObject | str]:
        events: list[JsonObject | str] = []
        while "\n\n" in self._buffer:
            raw_event, self._buffer = self._buffer.split("\n\n", 1)
            event = _parse_sse_event(raw_event)
            if event is not None:
                events.append(event)
        return events


def _parse_sse_event(raw_event: str) -> JsonObject | str | None:
    data_lines: list[str] = []
    for raw_line in raw_event.splitlines():
        if not raw_line or raw_line.startswith(":"):
            continue
        field, _, value = raw_line.partition(":")
        if field != "data":
            continue
        data_lines.append(value[1:] if value.startswith(" ") else value)
    if not data_lines:
        return None
    data = "\n".join(data_lines)
    if data.strip() == "[DONE]":
        return "[DONE]"
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return None
    return cast(JsonObject, parsed) if is_json_mapping(parsed) else None


def _int_field(payload: Mapping[str, JsonValue], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _openai_error_content(exc: ClaudeSidecarError) -> OpenAIErrorEnvelope:
    if is_json_mapping(exc.body):
        error = exc.body.get("error")
        if is_json_mapping(error):
            message = error.get("message")
            if isinstance(message, str) and message:
                return cast(OpenAIErrorEnvelope, exc.body)
    return openai_error("claude_sidecar_error", exc.message, error_type="upstream_error")


def _error_sse(error: OpenAIErrorEnvelope) -> bytes:
    data = json.dumps(error, ensure_ascii=True, separators=(",", ":"))
    return f"data: {data}\n\n".encode("utf-8")


async def _log_sidecar_request(
    *,
    api_key: ApiKeyData | None,
    model: str,
    started_at: float,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
    usage: SidecarUsage | None = None,
) -> None:
    try:
        async with get_background_session() as session:
            repo = RequestLogsRepository(session)
            await repo.add_log(
                account_id=None,
                request_id=get_request_id(),
                model=model,
                input_tokens=usage.input_tokens if usage else None,
                output_tokens=usage.output_tokens if usage else None,
                cached_input_tokens=usage.cached_input_tokens if usage else None,
                latency_ms=max(0, int((time.monotonic() - started_at) * 1000)),
                status=status,
                error_code=error_code,
                error_message=error_message,
                transport="http",
                api_key_id=api_key.id if api_key else None,
                source="claude_sidecar",
                failure_phase="sidecar" if status != "success" else None,
            )
    except Exception:
        logger.warning(
            "failed to write Claude sidecar request log key_id=%s request_id=%s",
            api_key.id if api_key else None,
            get_request_id(),
            exc_info=True,
        )


async def _finalize_or_release_sidecar_reservation(
    reservation: ApiKeyUsageReservationData | None,
    *,
    api_key: ApiKeyData | None,
    model: str,
    usage: SidecarUsage | None,
) -> None:
    if reservation is None:
        return
    try:
        async with get_background_session() as session:
            service = ApiKeysService(ApiKeysRepository(session))
            if usage is None:
                await service.release_usage_reservation(reservation.reservation_id)
                return
            await service.finalize_usage_reservation(
                reservation.reservation_id,
                model=model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cached_input_tokens=usage.cached_input_tokens,
                service_tier=None,
            )
    except Exception:
        logger.warning(
            "failed to settle Claude sidecar API key reservation key_id=%s request_id=%s",
            api_key.id if api_key else None,
            get_request_id(),
            exc_info=True,
        )


async def _release_sidecar_reservation(
    reservation: ApiKeyUsageReservationData | None,
    *,
    api_key: ApiKeyData | None,
) -> None:
    await _finalize_or_release_sidecar_reservation(
        reservation,
        api_key=api_key,
        model=reservation.model if reservation else "",
        usage=None,
    )
