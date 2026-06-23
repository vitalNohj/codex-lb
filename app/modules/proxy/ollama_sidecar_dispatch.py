from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import cast

from fastapi import Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.clients.ollama_sidecar import (
    OllamaSidecarClient,
    OllamaSidecarConfig,
    OllamaSidecarError,
    OllamaSidecarUnavailableError,
)
from app.core.config.settings_cache import get_settings_cache
from app.core.crypto import TokenEncryptor
from app.core.errors import OpenAIErrorEnvelope, openai_error
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.core.types import JsonObject, JsonValue
from app.core.utils.json_guards import is_json_list, is_json_mapping
from app.core.utils.request_id import get_request_id
from app.core.utils.sse import inject_sse_keepalives
from app.db.models import DashboardSettings
from app.db.session import get_background_session
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyData, ApiKeysService, ApiKeyUsageReservationData
from app.modules.proxy.claude_sidecar_dispatch import (
    SidecarUsage,
    reference_cost_from_sidecar_usage,
)
from app.modules.proxy.cursor_chat_compat import (
    apply_cursor_usage_fallback_to_response,
    stream_bytes_with_cursor_usage_fallback,
)
from app.modules.proxy.sidecar_routing import (
    SidecarRoutingEntry,
    parse_sidecar_full_models,
    parse_sidecar_prefixes,
)
from app.modules.request_logs.repository import RequestLogsRepository

logger = logging.getLogger(__name__)

OLLAMA_SIDECAR_SOURCE = "ollama_sidecar"


@dataclass(frozen=True, slots=True)
class OllamaChatPayload:
    body: dict[str, JsonValue]
    requested_reasoning_effort: str | None = None
    effective_reasoning_effort: str | None = None


def ollama_routing_entry(config: OllamaSidecarConfig) -> SidecarRoutingEntry:
    return SidecarRoutingEntry(
        provider="ollama",
        prefixes=config.prefixes,
        full_models=config.full_models,
    )


async def load_ollama_sidecar_config() -> OllamaSidecarConfig | None:
    try:
        dashboard_settings = await get_settings_cache().get()
    except Exception:
        logger.warning("failed to load dashboard settings for Ollama sidecar", exc_info=True)
        return None
    return ollama_sidecar_config_from_settings(dashboard_settings)


def ollama_sidecar_config_from_settings(settings: DashboardSettings) -> OllamaSidecarConfig:
    api_key = _decrypt_ollama_secret(settings.ollama_sidecar_api_key_encrypted)
    return OllamaSidecarConfig(
        enabled=bool(settings.ollama_sidecar_enabled),
        base_url=settings.ollama_sidecar_base_url.rstrip("/"),
        api_key=api_key,
        prefixes=parse_sidecar_prefixes(settings.ollama_sidecar_model_prefixes_json),
        full_models=parse_sidecar_full_models(settings.ollama_sidecar_full_models_json),
        connect_timeout_seconds=settings.ollama_sidecar_connect_timeout_seconds,
        request_timeout_seconds=settings.ollama_sidecar_request_timeout_seconds,
        models_cache_ttl_seconds=settings.ollama_sidecar_models_cache_ttl_seconds,
        default_reasoning_effort=settings.ollama_sidecar_default_reasoning_effort,
    )


def _decrypt_ollama_secret(encrypted: bytes | None) -> str | None:
    if not encrypted:
        return None
    try:
        return TokenEncryptor().decrypt(encrypted)
    except Exception:
        logger.warning("failed to decrypt Ollama sidecar API key", exc_info=True)
        return None


def build_ollama_chat_payload(
    payload: ChatCompletionsRequest,
    effective_model: str,
    default_reasoning_effort: str | None = None,
) -> OllamaChatPayload:
    body: dict[str, JsonValue] = {
        "model": effective_model.strip(),
        "stream": bool(payload.stream),
    }
    if payload.messages is not None:
        body["messages"] = [_ollama_message(message) for message in payload.messages if is_json_mapping(message)]
    tools = _ollama_tools(payload.tools)
    if tools:
        body["tools"] = tools
    response_format = _ollama_response_format(payload.response_format)
    if response_format is not None:
        body["format"] = response_format
    options = _ollama_options(payload)
    if options:
        body["options"] = options
    thinking = _ollama_thinking(payload)
    # Capture the client-requested effort (a string ``think``/effort value) for
    # request-log observability; a boolean ``think`` is not an effort label.
    requested_reasoning_effort = thinking.strip() if isinstance(thinking, str) and thinking.strip() else None
    override = default_reasoning_effort.strip() if default_reasoning_effort else None
    if override:
        # Configured override maps to Ollama's ``think`` field and forces the
        # value over any client-supplied thinking.
        thinking = override
    if thinking is not None:
        body["think"] = thinking
    effective_reasoning_effort = thinking.strip() if isinstance(thinking, str) and thinking.strip() else None
    return OllamaChatPayload(
        body=body,
        requested_reasoning_effort=requested_reasoning_effort,
        effective_reasoning_effort=effective_reasoning_effort,
    )


async def proxy_chat_to_ollama(
    request: Request,
    payload: ChatCompletionsRequest,
    *,
    effective_model: str,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    rate_limit_headers: Mapping[str, str],
    sse_keepalive_interval_seconds: float,
    client: OllamaSidecarClient,
    cursor_compat: bool = False,
    wire_model: str | None = None,
) -> Response:
    sidecar_payload = build_ollama_chat_payload(
        payload, wire_model or effective_model, client.config.default_reasoning_effort
    )
    requested_at = time.monotonic()
    if payload.stream:
        _ensure_ollama_stream_usage_requested(sidecar_payload.body)
        stream: AsyncIterator[bytes] = _ollama_stream_iterator(
            sidecar_payload.body,
            api_key=api_key,
            reservation=reservation,
            model=effective_model,
            started_at=requested_at,
            client=client,
            reasoning_effort=sidecar_payload.effective_reasoning_effort,
            requested_reasoning_effort=sidecar_payload.requested_reasoning_effort,
        )
        if cursor_compat:
            stream = stream_bytes_with_cursor_usage_fallback(
                stream,
                payload,
                source="ollama_sidecar_stream",
            )
        return StreamingResponse(
            inject_sse_keepalives(stream, sse_keepalive_interval_seconds),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", **dict(rate_limit_headers)},
        )

    try:
        upstream_body = await client.chat_completion(sidecar_payload.body)
    except OllamaSidecarUnavailableError:
        await _release_ollama_reservation(reservation, api_key=api_key)
        await _log_ollama_request(
            api_key=api_key,
            model=effective_model,
            started_at=requested_at,
            status="error",
            error_code="ollama_sidecar_unavailable",
            error_message="Ollama sidecar unavailable",
            reasoning_effort=sidecar_payload.effective_reasoning_effort,
            requested_reasoning_effort=sidecar_payload.requested_reasoning_effort,
        )
        return JSONResponse(
            status_code=503,
            content=openai_error(
                "ollama_sidecar_unavailable",
                "Ollama sidecar unavailable",
                error_type="upstream_error",
            ),
            headers=dict(rate_limit_headers),
        )
    except OllamaSidecarError as exc:
        await _release_ollama_reservation(reservation, api_key=api_key)
        await _log_ollama_request(
            api_key=api_key,
            model=effective_model,
            started_at=requested_at,
            status="error",
            error_code="ollama_sidecar_error",
            error_message=exc.message,
            reasoning_effort=sidecar_payload.effective_reasoning_effort,
            requested_reasoning_effort=sidecar_payload.requested_reasoning_effort,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_openai_error_content(exc),
            headers=dict(rate_limit_headers),
        )

    response_body = ollama_response_to_openai_chat_completion(upstream_body)
    usage = _usage_from_ollama(upstream_body)
    await _finalize_or_release_ollama_reservation(
        reservation,
        api_key=api_key,
        model=effective_model,
        usage=usage,
    )
    await _log_ollama_request(
        api_key=api_key,
        model=effective_model,
        started_at=requested_at,
        status="success",
        usage=usage,
        reasoning_effort=sidecar_payload.effective_reasoning_effort,
        requested_reasoning_effort=sidecar_payload.requested_reasoning_effort,
    )
    if cursor_compat and is_json_mapping(response_body):
        response_body = apply_cursor_usage_fallback_to_response(
            cast(dict[str, JsonValue], response_body),
            payload,
            source="ollama_sidecar_non_stream",
        )
    return JSONResponse(content=response_body, status_code=200, headers=dict(rate_limit_headers))


def ollama_response_to_openai_chat_completion(response: JsonValue) -> JsonObject:
    payload = response if is_json_mapping(response) else {}
    message = _mapping_field(payload, "message") or {}
    model = _str_field(payload, "model") or ""
    content = _message_content(message)
    tool_calls = _openai_tool_calls(message.get("tool_calls"))
    openai_message: dict[str, JsonValue] = {
        "role": "assistant",
        "content": content,
    }
    if tool_calls:
        openai_message["tool_calls"] = tool_calls
    usage = _ollama_usage_object(payload)
    return {
        "id": _str_field(payload, "id") or f"chatcmpl-ollama-{get_request_id()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": openai_message,
                "finish_reason": _finish_reason(payload, has_tool_calls=bool(tool_calls)),
            }
        ],
        "usage": usage,
    }


async def _ollama_stream_iterator(
    payload: Mapping[str, JsonValue],
    *,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    model: str,
    started_at: float,
    client: OllamaSidecarClient,
    reasoning_effort: str | None = None,
    requested_reasoning_effort: str | None = None,
) -> AsyncIterator[bytes]:
    usage: SidecarUsage | None = None
    completed = False
    settled = False
    stream_id = f"chatcmpl-ollama-{get_request_id()}"
    created = int(time.time())
    try:
        yield _sse(
            _chunk(
                stream_id=stream_id,
                created=created,
                model=model,
                delta={"role": "assistant"},
                finish_reason=None,
            )
        )
        async for part in client.stream_chat_completion(payload):
            part_mapping = part if is_json_mapping(part) else {}
            message = _mapping_field(part_mapping, "message") or {}
            content = _message_content(message)
            tool_calls = _openai_tool_calls(message.get("tool_calls"))
            if content:
                yield _sse(
                    _chunk(
                        stream_id=stream_id,
                        created=created,
                        model=model,
                        delta={"content": content},
                        finish_reason=None,
                    )
                )
            if tool_calls:
                yield _sse(
                    _chunk(
                        stream_id=stream_id,
                        created=created,
                        model=model,
                        delta={"tool_calls": _tool_call_deltas(tool_calls)},
                        finish_reason=None,
                    )
                )
            part_usage = _usage_from_ollama(part_mapping)
            if part_usage is not None:
                usage = part_usage
            if bool(part_mapping.get("done")):
                completed = True
                yield _sse(
                    _chunk(
                        stream_id=stream_id,
                        created=created,
                        model=model,
                        delta={},
                        finish_reason=_finish_reason(part_mapping, has_tool_calls=bool(tool_calls)),
                    )
                )
        if usage is not None and _include_usage(payload):
            yield _sse(
                {
                    "id": stream_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [],
                    "usage": _usage_object(usage),
                }
            )
        yield b"data: [DONE]\n\n"
    except OllamaSidecarUnavailableError:
        await _release_ollama_reservation(reservation, api_key=api_key)
        await _log_ollama_request(
            api_key=api_key,
            model=model,
            started_at=started_at,
            status="error",
            error_code="ollama_sidecar_unavailable",
            error_message="Ollama sidecar unavailable",
            reasoning_effort=reasoning_effort,
            requested_reasoning_effort=requested_reasoning_effort,
        )
        settled = True
        yield _error_sse(
            openai_error(
                "ollama_sidecar_unavailable",
                "Ollama sidecar unavailable",
                error_type="upstream_error",
            )
        )
        yield b"data: [DONE]\n\n"
    except OllamaSidecarError as exc:
        await _release_ollama_reservation(reservation, api_key=api_key)
        await _log_ollama_request(
            api_key=api_key,
            model=model,
            started_at=started_at,
            status="error",
            error_code="ollama_sidecar_error",
            error_message=exc.message,
            reasoning_effort=reasoning_effort,
            requested_reasoning_effort=requested_reasoning_effort,
        )
        settled = True
        yield _error_sse(_openai_error_content(exc))
        yield b"data: [DONE]\n\n"
    except BaseException as exc:
        await _release_ollama_reservation(reservation, api_key=api_key)
        await _log_ollama_request(
            api_key=api_key,
            model=model,
            started_at=started_at,
            status="error",
            error_code="ollama_sidecar_stream_interrupted",
            error_message=str(exc) or exc.__class__.__name__,
            reasoning_effort=reasoning_effort,
            requested_reasoning_effort=requested_reasoning_effort,
        )
        settled = True
        raise
    finally:
        if not settled:
            usage_to_settle = usage if completed else None
            await _finalize_or_release_ollama_reservation(
                reservation,
                api_key=api_key,
                model=model,
                usage=usage_to_settle,
            )
            await _log_ollama_request(
                api_key=api_key,
                model=model,
                started_at=started_at,
                status="success" if completed else "error",
                error_code=None if completed else "ollama_sidecar_stream_incomplete",
                usage=usage_to_settle,
                reasoning_effort=reasoning_effort,
                requested_reasoning_effort=requested_reasoning_effort,
            )


def _ollama_message(message: Mapping[str, JsonValue]) -> JsonObject:
    role = message.get("role")
    role_name = role if role in {"system", "user", "assistant", "tool"} else "user"
    normalized: dict[str, JsonValue] = {
        "role": cast(str, role_name),
        "content": _content_text(message.get("content")),
    }
    if role_name == "tool":
        tool_name = message.get("name")
        if isinstance(tool_name, str) and tool_name:
            normalized["tool_name"] = tool_name
        tool_call_id = message.get("tool_call_id")
        if isinstance(tool_call_id, str) and tool_call_id:
            normalized["tool_call_id"] = tool_call_id
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        normalized["tool_calls"] = cast(JsonValue, tool_calls)
    return normalized


def _content_text(content: JsonValue) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if is_json_list(content):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
                continue
            if is_json_mapping(part):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return json.dumps(content, ensure_ascii=False, separators=(",", ":"))


def _ollama_tools(tools: list[JsonValue]) -> JsonValue | None:
    normalized: list[JsonValue] = []
    for tool in tools:
        if not is_json_mapping(tool):
            continue
        function = tool.get("function")
        if not is_json_mapping(function):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        next_tool: dict[str, JsonValue] = {
            "type": "function",
            "function": {
                "name": name,
                "description": function.get("description"),
                "parameters": function.get("parameters"),
            },
        }
        normalized.append(next_tool)
    return normalized or None


def _ollama_response_format(response_format: JsonValue) -> JsonValue | None:
    if not is_json_mapping(response_format):
        return None
    format_type = response_format.get("type")
    if format_type == "json_object":
        return "json"
    if format_type != "json_schema":
        return None
    json_schema = response_format.get("json_schema")
    if not is_json_mapping(json_schema):
        return None
    schema = json_schema.get("schema")
    return schema if is_json_mapping(schema) else None


def _ollama_options(payload: ChatCompletionsRequest) -> JsonObject:
    options: dict[str, JsonValue] = {}
    if payload.temperature is not None:
        options["temperature"] = payload.temperature
    if payload.top_p is not None:
        options["top_p"] = payload.top_p
    max_tokens = payload.max_completion_tokens if payload.max_completion_tokens is not None else payload.max_tokens
    if max_tokens is not None:
        options["num_predict"] = max_tokens
    if payload.stop is not None:
        options["stop"] = payload.stop
    return options


def _ollama_thinking(payload: ChatCompletionsRequest) -> JsonValue | None:
    extra = getattr(payload, "__pydantic_extra__", None)
    if not isinstance(extra, dict):
        return None
    thinking = extra.get("thinking")
    if isinstance(thinking, bool | str):
        return thinking
    reasoning = extra.get("reasoning")
    if is_json_mapping(reasoning):
        effort = reasoning.get("effort")
        if isinstance(effort, str):
            return effort
    return None


def _ensure_ollama_stream_usage_requested(payload: dict[str, JsonValue]) -> None:
    raw_options = payload.get("stream_options")
    options = dict(raw_options) if is_json_mapping(raw_options) else {}
    options["include_usage"] = True
    payload["stream_options"] = options


def _openai_error_content(exc: OllamaSidecarError) -> OpenAIErrorEnvelope:
    if is_json_mapping(exc.body):
        error = exc.body.get("error")
        if is_json_mapping(error):
            message = error.get("message")
            if isinstance(message, str) and message:
                return cast(OpenAIErrorEnvelope, exc.body)
    return openai_error("ollama_sidecar_error", exc.message, error_type="upstream_error")


def _finish_reason(payload: Mapping[str, JsonValue], *, has_tool_calls: bool) -> str:
    if has_tool_calls:
        return "tool_calls"
    done_reason = _str_field(payload, "done_reason") or _str_field(payload, "doneReason")
    if done_reason in {"length", "stop"}:
        return done_reason
    if done_reason in {"load", "unload"}:
        return "stop"
    return "length" if done_reason == "max_tokens" else "stop"


def _ollama_usage_object(payload: Mapping[str, JsonValue]) -> JsonObject:
    usage = _usage_from_ollama(payload)
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    return _usage_object(usage)


def _usage_from_ollama(payload: Mapping[str, JsonValue]) -> SidecarUsage | None:
    input_tokens = _int_field(payload, "prompt_eval_count")
    output_tokens = _int_field(payload, "eval_count")
    if input_tokens is None and output_tokens is None:
        usage = payload.get("usage")
        if is_json_mapping(usage):
            input_tokens = _int_field(usage, "prompt_tokens")
            output_tokens = _int_field(usage, "completion_tokens")
    if input_tokens is None or output_tokens is None:
        return None
    return SidecarUsage(input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=None)


def _usage_object(usage: SidecarUsage) -> JsonObject:
    return {
        "prompt_tokens": usage.input_tokens,
        "completion_tokens": usage.output_tokens,
        "total_tokens": usage.input_tokens + usage.output_tokens,
    }


def _chunk(
    *,
    stream_id: str,
    created: int,
    model: str,
    delta: JsonObject,
    finish_reason: str | None,
) -> JsonObject:
    return {
        "id": stream_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def _message_content(message: Mapping[str, JsonValue]) -> str:
    content = message.get("content")
    return content if isinstance(content, str) else ""


def _openai_tool_calls(value: JsonValue) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    calls: list[JsonObject] = []
    for index, entry in enumerate(value):
        if not is_json_mapping(entry):
            continue
        function = entry.get("function")
        if is_json_mapping(function):
            name = function.get("name")
            raw_arguments = function.get("arguments")
        else:
            name = entry.get("name")
            raw_arguments = entry.get("arguments")
        if not isinstance(name, str) or not name:
            continue
        call_id = entry.get("id")
        calls.append(
            {
                "id": call_id if isinstance(call_id, str) and call_id else f"call_{index}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": _tool_arguments(raw_arguments),
                },
            }
        )
    return calls


def _tool_call_deltas(tool_calls: list[JsonObject]) -> list[JsonObject]:
    deltas: list[JsonObject] = []
    for index, tool_call in enumerate(tool_calls):
        delta = dict(tool_call)
        delta["index"] = index
        deltas.append(delta)
    return deltas


def _tool_arguments(value: JsonValue) -> str:
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _mapping_field(payload: Mapping[str, JsonValue], field: str) -> Mapping[str, JsonValue] | None:
    value = payload.get(field)
    return value if is_json_mapping(value) else None


def _str_field(payload: Mapping[str, JsonValue], field: str) -> str | None:
    value = payload.get(field)
    return value if isinstance(value, str) and value else None


def _int_field(payload: Mapping[str, JsonValue], field: str) -> int | None:
    value = payload.get(field)
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    return None


def _include_usage(payload: Mapping[str, JsonValue]) -> bool:
    options = payload.get("stream_options")
    return is_json_mapping(options) and options.get("include_usage") is True


def _sse(payload: JsonObject) -> bytes:
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return f"data: {data}\n\n".encode("utf-8")


def _error_sse(error: OpenAIErrorEnvelope) -> bytes:
    data = json.dumps(error, ensure_ascii=True, separators=(",", ":"))
    return f"data: {data}\n\n".encode("utf-8")


async def _log_ollama_request(
    *,
    api_key: ApiKeyData | None,
    model: str,
    started_at: float,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
    usage: SidecarUsage | None = None,
    reasoning_effort: str | None = None,
    requested_reasoning_effort: str | None = None,
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
                reasoning_effort=reasoning_effort,
                requested_reasoning_effort=requested_reasoning_effort,
                transport="http",
                api_key_id=api_key.id if api_key else None,
                source=OLLAMA_SIDECAR_SOURCE,
                failure_phase="sidecar" if status != "success" else None,
                cost_usd=usage.cost_usd if usage else None,
                reference_cost_usd=reference_cost_from_sidecar_usage(model, usage),
            )
    except Exception:
        logger.warning(
            "failed to write Ollama sidecar request log key_id=%s request_id=%s",
            api_key.id if api_key else None,
            get_request_id(),
            exc_info=True,
        )


async def _finalize_or_release_ollama_reservation(
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
            "failed to settle Ollama sidecar API key reservation key_id=%s request_id=%s",
            api_key.id if api_key else None,
            get_request_id(),
            exc_info=True,
        )


async def _release_ollama_reservation(
    reservation: ApiKeyUsageReservationData | None,
    *,
    api_key: ApiKeyData | None,
) -> None:
    await _finalize_or_release_ollama_reservation(
        reservation,
        api_key=api_key,
        model=reservation.model if reservation else "",
        usage=None,
    )
