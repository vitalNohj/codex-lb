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
from app.core.usage.pricing import UsageTokens
from app.core.usage.runtime_pricing import calculate_reference_cost
from app.core.utils.json_guards import is_json_mapping
from app.core.utils.request_id import get_request_id
from app.core.utils.sse import inject_sse_keepalives
from app.db.models import DashboardSettings
from app.db.session import get_background_session
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyData, ApiKeysService, ApiKeyUsageReservationData
from app.modules.proxy.cursor_chat_compat import (
    apply_cursor_usage_fallback_to_response,
    cursor_context_limit_usage_completion,
    cursor_context_limit_usage_sse_chunks,
    is_context_length_error,
    is_context_length_error_envelope,
    stream_bytes_with_cursor_usage_fallback,
)
from app.modules.proxy.deepseek_v4_compat import (
    DeepSeekScope,
)
from app.modules.proxy.deepseek_v4_compat import (
    capture_non_streaming as deepseek_capture_non_streaming,
)
from app.modules.proxy.deepseek_v4_compat import (
    make_stream_recorder as deepseek_make_stream_recorder,
)
from app.modules.proxy.deepseek_v4_compat import (
    resolve_scope as deepseek_resolve_scope,
)
from app.modules.proxy.sidecar_model_profiles import (
    apply_sidecar_model_profile_with_suffix_effort,
    read_reasoning_effort,
    set_reasoning_effort_override,
)
from app.modules.proxy.sidecar_routing import (
    SidecarRoutingEntry,
    parse_sidecar_full_models,
    parse_sidecar_prefixes,
)
from app.modules.proxy.sidecar_tool_mapper import (
    SidecarSseToolNameRewriter,
    map_sidecar_chat_tool_names,
    reverse_sidecar_tool_names_in_response,
)
from app.modules.request_logs.repository import RequestLogsRepository

logger = logging.getLogger(__name__)

_SIDECAR_TOOL_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
_SIDECAR_TOOL_ID_INVALID_CHAR = re.compile(r"[^a-zA-Z0-9_-]")
_SIDECAR_TOOL_CALL_ID_FIELDS = ("tool_call_id", "toolCallId", "call_id")
_SIDECAR_TOOL_CONTENT_CALL_ID_TYPES = frozenset(
    {"function_call", "custom_tool_call", "function_call_output", "custom_tool_call_output"}
)
_SIDECAR_MESSAGE_CONTINUATION = "Continue."


@dataclass(frozen=True, slots=True)
class SidecarUsage:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    cost_usd: float | None = None


@dataclass(frozen=True, slots=True)
class SidecarChatPayload:
    body: dict[str, JsonValue]
    reverse_tool_names: dict[str, str]
    requested_reasoning_effort: str | None = None
    effective_reasoning_effort: str | None = None


def claude_routing_entry(config: ClaudeSidecarConfig) -> SidecarRoutingEntry:
    return SidecarRoutingEntry(
        provider="claude",
        prefixes=config.prefixes,
        full_models=config.full_models,
    )


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
        prefixes=parse_sidecar_prefixes(settings.claude_sidecar_model_prefixes_json),
        connect_timeout_seconds=settings.claude_sidecar_connect_timeout_seconds,
        request_timeout_seconds=settings.claude_sidecar_request_timeout_seconds,
        models_cache_ttl_seconds=settings.claude_sidecar_models_cache_ttl_seconds,
        full_models=parse_sidecar_full_models(settings.claude_sidecar_full_models_json),
        management_key=management_key,
        default_reasoning_effort=settings.claude_sidecar_default_reasoning_effort,
    )


def _decrypt_sidecar_secret(encrypted: bytes | None, *, label: str) -> str | None:
    if not encrypted:
        return None
    try:
        return TokenEncryptor().decrypt(encrypted)
    except Exception:
        logger.warning("failed to decrypt Claude sidecar %s", label, exc_info=True)
        return None


def sanitize_sidecar_chat_messages(body: dict[str, JsonValue]) -> None:
    messages = body.get("messages")
    if not isinstance(messages, list):
        return
    filtered = _filter_sidecar_messages(messages)
    filtered = _ensure_sidecar_trailing_user_message(filtered)
    body["messages"] = filtered


def normalize_sidecar_cursor_tool_history(body: dict[str, JsonValue]) -> None:
    messages = body.get("messages")
    if not isinstance(messages, list):
        return
    normalized: list[JsonValue] = []
    for raw_message in messages:
        if not is_json_mapping(raw_message):
            continue
        message = cast(dict[str, JsonValue], raw_message)
        role = message.get("role")
        if role == "assistant":
            normalized.append(_normalize_sidecar_assistant_tool_use_message(message))
            continue
        if role == "user":
            normalized.extend(_normalize_sidecar_user_tool_result_message(message))
            continue
        normalized.append(message)
    body["messages"] = normalized


def _normalize_sidecar_assistant_tool_use_message(message: dict[str, JsonValue]) -> dict[str, JsonValue]:
    content = message.get("content")
    if not isinstance(content, list):
        return message

    text_parts: list[JsonValue] = []
    generated_tool_calls: list[JsonValue] = []
    for part in content:
        if not is_json_mapping(part):
            text_parts.append(part)
            continue
        part_dict = cast(dict[str, JsonValue], part)
        if part_dict.get("type") != "tool_use":
            text_parts.append(part)
            continue
        tool_call = _sidecar_tool_call_from_tool_use(part_dict)
        if tool_call is not None:
            generated_tool_calls.append(tool_call)

    if not generated_tool_calls:
        return {**message, "content": _normalize_sidecar_content_parts(content)}

    normalized = {**message, "content": _sidecar_text_from_content_parts(text_parts) or None}
    existing_tool_calls = message.get("tool_calls")
    if isinstance(existing_tool_calls, list):
        normalized["tool_calls"] = [*existing_tool_calls, *generated_tool_calls]
    else:
        normalized["tool_calls"] = generated_tool_calls
    return normalized


def _sidecar_tool_call_from_tool_use(part: dict[str, JsonValue]) -> JsonValue | None:
    tool_id = part.get("id")
    tool_name = part.get("name")
    if not isinstance(tool_id, str) or not tool_id:
        return None
    if not isinstance(tool_name, str) or not tool_name:
        return None
    return {
        "id": tool_id,
        "type": "function",
        "function": {
            "name": tool_name,
            "arguments": _sidecar_tool_arguments(part.get("input")),
        },
    }


def _sidecar_tool_arguments(value: JsonValue) -> str:
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _normalize_sidecar_user_tool_result_message(message: dict[str, JsonValue]) -> list[JsonValue]:
    content = message.get("content")
    content_dict = cast(dict[str, JsonValue], content) if is_json_mapping(content) else None
    if content_dict is not None and content_dict.get("type") == "tool_result":
        return _sidecar_tool_message_from_tool_result(message, content_dict)
    if not isinstance(content, list):
        return [{**message, "content": _normalize_sidecar_content_part(content)}]

    normalized: list[JsonValue] = []
    message_parts: list[JsonValue] = []
    for part in content:
        part_dict = cast(dict[str, JsonValue], part) if is_json_mapping(part) else None
        if part_dict is None or part_dict.get("type") != "tool_result":
            message_parts.append(_normalize_sidecar_content_part(part))
            continue
        if message_parts:
            normalized.append({**message, "content": message_parts})
            message_parts = []
        normalized.extend(_sidecar_tool_message_from_tool_result(message, part_dict))
    if message_parts:
        normalized.append({**message, "content": message_parts})
    return normalized


def _sidecar_tool_message_from_tool_result(
    message: dict[str, JsonValue],
    part: dict[str, JsonValue],
) -> list[JsonValue]:
    tool_use_id = part.get("tool_use_id")
    if not isinstance(tool_use_id, str) or not tool_use_id:
        return []
    return [
        {
            "role": "tool",
            "tool_call_id": tool_use_id,
            "content": _sidecar_tool_result_output(part.get("content")),
        }
    ]


def _normalize_sidecar_content_parts(content: list[JsonValue]) -> list[JsonValue]:
    return [_normalize_sidecar_content_part(part) for part in content]


def _normalize_sidecar_content_part(part: JsonValue) -> JsonValue:
    if not is_json_mapping(part):
        return part
    part_dict = dict(cast(dict[str, JsonValue], part))
    part_type = part_dict.get("type")
    if part_type in {"input_text", "output_text"}:
        part_dict["type"] = "text"
    elif part_type == "image":
        converted = _sidecar_image_part_to_image_url(part_dict)
        if converted is not None:
            return converted
    return cast(JsonValue, part_dict)


def _sidecar_image_part_to_image_url(part: dict[str, JsonValue]) -> JsonValue | None:
    """Convert an Anthropic-native image block into the OpenAI ``image_url``
    data-URL shape that CLIProxyAPI accepts.

    Anthropic shape (sent by Cursor vision input):
        {"type": "image", "source": {"type": "base64", "media_type": ..., "data": ...}}
        {"type": "image", "source": {"type": "url", "url": ...}}
    Returns ``None`` if the source is unrecognized so the caller leaves the
    part untouched.
    """
    source = part.get("source")
    if not is_json_mapping(source):
        return None
    source_dict = cast(dict[str, JsonValue], source)
    source_type = source_dict.get("type")
    if source_type == "base64":
        media_type = source_dict.get("media_type")
        data = source_dict.get("data")
        if not isinstance(media_type, str) or not isinstance(data, str):
            return None
        return {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{data}"}}
    if source_type == "url":
        url = source_dict.get("url")
        if not isinstance(url, str):
            return None
        return {"type": "image_url", "image_url": {"url": url}}
    return None


def _sidecar_text_from_content_parts(parts: list[JsonValue]) -> str:
    text: list[str] = []
    for part in parts:
        if isinstance(part, str):
            text.append(part)
            continue
        if not is_json_mapping(part):
            continue
        part_dict = cast(dict[str, JsonValue], part)
        part_type = part_dict.get("type")
        if part_type in {"text", "input_text", "output_text"}:
            value = part_dict.get("text")
            if isinstance(value, str):
                text.append(value)
    return "".join(text)


def _sidecar_tool_result_output(content: JsonValue) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        output = _sidecar_text_from_content_parts(content)
        return output if output or not content else json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    if is_json_mapping(content):
        content_dict = cast(dict[str, JsonValue], content)
        text = content_dict.get("text")
        if isinstance(text, str):
            return text
    return json.dumps(content, ensure_ascii=False, separators=(",", ":"))


def _filter_sidecar_messages(messages: list[JsonValue]) -> list[JsonValue]:
    filtered: list[JsonValue] = []
    seen_tool_call_ids: set[str] = set()
    for raw_message in messages:
        if not is_json_mapping(raw_message):
            continue
        message = cast(dict[str, JsonValue], raw_message)
        role = message.get("role")
        if role == "assistant":
            _register_sidecar_assistant_tool_call_ids(message, seen_tool_call_ids)
        if role == "user":
            message = _filter_sidecar_user_tool_result_parts(message, seen_tool_call_ids)
        if not _sidecar_message_has_substance(message):
            continue
        if role == "tool" and not _sidecar_tool_message_is_referenced(message, seen_tool_call_ids):
            continue
        filtered.append(message)
    return filtered


def _ensure_sidecar_trailing_user_message(messages: list[JsonValue]) -> list[JsonValue]:
    if not messages:
        return messages
    last = messages[-1]
    if not is_json_mapping(last):
        return messages
    if cast(dict[str, JsonValue], last).get("role") != "assistant":
        return messages
    return [
        *messages,
        {"role": "user", "content": _SIDECAR_MESSAGE_CONTINUATION},
    ]


def _register_sidecar_assistant_tool_call_ids(
    message: dict[str, JsonValue],
    seen_tool_call_ids: set[str],
) -> None:
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for tool_call in tool_calls:
            if not is_json_mapping(tool_call):
                continue
            tool_call_id = cast(dict[str, JsonValue], tool_call).get("id")
            if isinstance(tool_call_id, str) and tool_call_id:
                seen_tool_call_ids.add(tool_call_id)
    function_call = message.get("function_call")
    if is_json_mapping(function_call):
        function_call_id = cast(dict[str, JsonValue], function_call).get("id")
        if isinstance(function_call_id, str) and function_call_id:
            seen_tool_call_ids.add(function_call_id)
    content = message.get("content")
    if isinstance(content, list):
        for part in content:
            if not is_json_mapping(part):
                continue
            part_dict = cast(dict[str, JsonValue], part)
            if part_dict.get("type") == "tool_use":
                tool_use_id = part_dict.get("id")
                if isinstance(tool_use_id, str) and tool_use_id:
                    seen_tool_call_ids.add(tool_use_id)


def _sidecar_tool_message_is_referenced(
    message: dict[str, JsonValue],
    seen_tool_call_ids: set[str],
) -> bool:
    for field in _SIDECAR_TOOL_CALL_ID_FIELDS:
        tool_call_id = message.get(field)
        if isinstance(tool_call_id, str) and tool_call_id in seen_tool_call_ids:
            return True
    return False


def _filter_sidecar_user_tool_result_parts(
    message: dict[str, JsonValue],
    seen_tool_call_ids: set[str],
) -> dict[str, JsonValue]:
    content = message.get("content")
    if is_json_mapping(content):
        content_dict = cast(dict[str, JsonValue], content)
        if content_dict.get("type") != "tool_result":
            return message
        tool_use_id = content_dict.get("tool_use_id")
        if isinstance(tool_use_id, str) and tool_use_id in seen_tool_call_ids:
            return message
        return {**message, "content": []}
    if not isinstance(content, list):
        return message
    filtered_content: list[JsonValue] = []
    changed = False
    for part in content:
        if not is_json_mapping(part):
            filtered_content.append(part)
            continue
        part_dict = cast(dict[str, JsonValue], part)
        if part_dict.get("type") != "tool_result":
            filtered_content.append(part)
            continue
        tool_use_id = part_dict.get("tool_use_id")
        if isinstance(tool_use_id, str) and tool_use_id in seen_tool_call_ids:
            filtered_content.append(part)
            continue
        changed = True
    if not changed:
        return message
    return {**message, "content": filtered_content}


def _sidecar_message_has_substance(message: dict[str, JsonValue]) -> bool:
    role = message.get("role")
    if role == "tool":
        return _sidecar_tool_message_is_present(message)
    if role == "assistant":
        if message.get("tool_calls") or message.get("function_call"):
            return True
        return not _sidecar_content_is_empty(message.get("content"))
    return not _sidecar_content_is_empty(message.get("content"))


def _sidecar_tool_message_is_present(message: dict[str, JsonValue]) -> bool:
    for field in _SIDECAR_TOOL_CALL_ID_FIELDS:
        tool_call_id = message.get(field)
        if isinstance(tool_call_id, str) and tool_call_id:
            return True
    return not _sidecar_content_is_empty(message.get("content"))


def _sidecar_content_is_empty(content: JsonValue) -> bool:
    if content is None:
        return True
    if isinstance(content, str):
        return not content.strip()
    if is_json_mapping(content):
        return _sidecar_content_part_is_empty(content)
    if isinstance(content, list):
        if not content:
            return True
        return all(_sidecar_content_part_is_empty(part) for part in content)
    return False


def _sidecar_content_part_is_empty(part: JsonValue) -> bool:
    if isinstance(part, str):
        return not part.strip()
    if not is_json_mapping(part):
        return False
    part_dict = cast(dict[str, JsonValue], part)
    part_type = part_dict.get("type")
    if part_type in {"text", "input_text", "output_text"}:
        text = part_dict.get("text")
        return not isinstance(text, str) or not text.strip()
    if part_type in {"tool_use", "tool_result", "image", "image_url", "input_image"}:
        return False
    return False


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


def sanitize_sidecar_forward_payload(body: dict[str, JsonValue]) -> None:
    reasoning = body.get("reasoning")
    if isinstance(reasoning, dict):
        reasoning_dict = cast(dict[str, JsonValue], reasoning)
        effort = reasoning_dict.get("effort")
        if isinstance(effort, str) and effort.strip() and not isinstance(body.get("reasoning_effort"), str):
            body["reasoning_effort"] = effort.strip()
        if isinstance(body.get("reasoning_effort"), str) and body["reasoning_effort"].strip():
            body.pop("reasoning", None)
    for key in ("previous_response_id", "truncation", "user", "text", "metadata"):
        body.pop(key, None)


def build_sidecar_chat_payload(
    payload: ChatCompletionsRequest,
    effective_model: str,
    config: ClaudeSidecarConfig,
) -> SidecarChatPayload:
    body = cast(dict[str, JsonValue], payload.model_dump(mode="json", exclude_none=True))
    # Capture the client-requested effort before the model profile or override
    # mutates it, so request logs can record requested-vs-effective.
    requested_reasoning_effort = read_reasoning_effort(body)
    # The unified resolver already produced the wire model (prefix stripped per
    # the matched prefix's strip flag); apply the canonical-model + reasoning
    # effort profile to that wire model.
    _, suffix_effort_applied = apply_sidecar_model_profile_with_suffix_effort(
        body, stripped_model=effective_model
    )
    # The configured override forces the provider effort over any client-sent
    # value, but an explicit model-name suffix is the highest precedence, so the
    # override only applies when the model name carried no effort suffix.
    if not suffix_effort_applied:
        set_reasoning_effort_override(body, config.default_reasoning_effort)
    sanitize_sidecar_forward_payload(body)
    effective_reasoning_effort = read_reasoning_effort(body)
    normalize_sidecar_cursor_tool_history(body)
    sanitize_sidecar_chat_tool_ids(body)
    sanitize_sidecar_chat_messages(body)
    tool_map = map_sidecar_chat_tool_names(body)
    return SidecarChatPayload(
        body=body,
        reverse_tool_names=tool_map.reverse_tool_names,
        requested_reasoning_effort=requested_reasoning_effort,
        effective_reasoning_effort=effective_reasoning_effort,
    )


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
    cursor_compat: bool = False,
    wire_model: str | None = None,
) -> Response:
    # ``effective_model`` is used for reservations/logging; ``wire_model`` (the
    # resolver's stripped model) shapes the forwarded payload.
    sidecar_payload = build_sidecar_chat_payload(payload, wire_model or effective_model, client.config)
    deepseek_scope = deepseek_resolve_scope(
        effective_model=effective_model,
        provider="claude",
        sidecar_body=sidecar_payload.body,
        api_key_id=api_key.id if api_key else None,
    )
    requested_at = time.monotonic()
    if payload.stream:
        ensure_stream_usage_requested(sidecar_payload.body)
        stream: AsyncIterator[bytes] = _sidecar_stream_iterator(
            sidecar_payload.body,
            reverse_tool_names=sidecar_payload.reverse_tool_names,
            api_key=api_key,
            reservation=reservation,
            model=effective_model,
            started_at=requested_at,
            client=client,
            request_payload=payload,
            cursor_compat=cursor_compat,
            rate_limit_headers=rate_limit_headers,
            deepseek_scope=deepseek_scope,
            reasoning_effort=sidecar_payload.effective_reasoning_effort,
            requested_reasoning_effort=sidecar_payload.requested_reasoning_effort,
        )
        if cursor_compat:
            stream = stream_bytes_with_cursor_usage_fallback(
                stream,
                payload,
                source="claude_sidecar_stream",
            )
        return StreamingResponse(
            inject_sse_keepalives(
                stream,
                sse_keepalive_interval_seconds,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", **dict(rate_limit_headers)},
        )

    try:
        response_body = await client.chat_completion(sidecar_payload.body)
    except ClaudeSidecarUnavailableError:
        await _release_sidecar_reservation(reservation, api_key=api_key)
        await _log_sidecar_request(
            api_key=api_key,
            model=effective_model,
            started_at=requested_at,
            status="error",
            error_code="claude_sidecar_unavailable",
            error_message="Claude sidecar unavailable",
            reasoning_effort=sidecar_payload.effective_reasoning_effort,
            requested_reasoning_effort=sidecar_payload.requested_reasoning_effort,
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
        if cursor_compat and _is_sidecar_context_length_error(exc):
            await _release_sidecar_reservation(reservation, api_key=api_key)
            return cursor_context_limit_usage_completion(
                payload,
                headers=dict(rate_limit_headers),
            )
        await _release_sidecar_reservation(reservation, api_key=api_key)
        await _log_sidecar_request(
            api_key=api_key,
            model=effective_model,
            started_at=requested_at,
            status="error",
            error_code="claude_sidecar_error",
            error_message=exc.message,
            reasoning_effort=sidecar_payload.effective_reasoning_effort,
            requested_reasoning_effort=sidecar_payload.requested_reasoning_effort,
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
        reasoning_effort=sidecar_payload.effective_reasoning_effort,
        requested_reasoning_effort=sidecar_payload.requested_reasoning_effort,
    )
    if deepseek_scope is not None:
        deepseek_capture_non_streaming(deepseek_scope, response_body)
    relay_body = reverse_sidecar_tool_names_in_response(
        response_body,
        sidecar_payload.reverse_tool_names,
    )
    if cursor_compat and is_json_mapping(relay_body):
        relay_body = apply_cursor_usage_fallback_to_response(
            cast(dict[str, JsonValue], relay_body),
            payload,
            source="sidecar_non_stream",
        )
    return JSONResponse(content=relay_body, status_code=200, headers=dict(rate_limit_headers))


async def _sidecar_stream_iterator(
    payload: Mapping[str, JsonValue],
    *,
    reverse_tool_names: dict[str, str],
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    model: str,
    started_at: float,
    client: ClaudeSidecarClient,
    request_payload: ChatCompletionsRequest,
    cursor_compat: bool,
    rate_limit_headers: Mapping[str, str],
    deepseek_scope: DeepSeekScope | None = None,
    reasoning_effort: str | None = None,
    requested_reasoning_effort: str | None = None,
) -> AsyncIterator[bytes]:
    usage: SidecarUsage | None = None
    completed = False
    settled = False
    # Observe the raw (pre tool-name-reversal) chunks so the DeepSeek reasoning
    # cache key uses forward-sanitized tool names, matching re-injection.
    deepseek_recorder = (
        deepseek_make_stream_recorder(deepseek_scope) if deepseek_scope is not None else None
    )
    try:
        async with client.stream_chat_completion(payload) as chunks:
            decoder = _SseUsageDecoder()
            tool_name_rewriter = SidecarSseToolNameRewriter(reverse_tool_names)
            async for raw_chunk in chunks:
                if deepseek_recorder is not None:
                    deepseek_recorder.record(raw_chunk)
                for event in decoder.feed(raw_chunk.decode("utf-8", errors="ignore")):
                    if event == "[DONE]":
                        completed = True
                        continue
                    event_usage = extract_usage(event)
                    if event_usage is not None:
                        usage = event_usage
                for rewritten_chunk in tool_name_rewriter.feed(raw_chunk):
                    yield rewritten_chunk
            for rewritten_chunk in tool_name_rewriter.flush():
                yield rewritten_chunk
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
            reasoning_effort=reasoning_effort,
            requested_reasoning_effort=requested_reasoning_effort,
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
        if cursor_compat and _is_sidecar_context_length_error(exc):
            await _release_sidecar_reservation(reservation, api_key=api_key)
            settled = True
            completed = True
            for chunk in cursor_context_limit_usage_sse_chunks(request_payload):
                yield chunk
            return
        await _release_sidecar_reservation(reservation, api_key=api_key)
        await _log_sidecar_request(
            api_key=api_key,
            model=model,
            started_at=started_at,
            status="error",
            error_code="claude_sidecar_error",
            error_message=exc.message,
            reasoning_effort=reasoning_effort,
            requested_reasoning_effort=requested_reasoning_effort,
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
            reasoning_effort=reasoning_effort,
            requested_reasoning_effort=requested_reasoning_effort,
        )
        settled = True
        raise
    finally:
        if deepseek_recorder is not None:
            deepseek_recorder.commit()
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
                reasoning_effort=reasoning_effort,
                requested_reasoning_effort=requested_reasoning_effort,
            )


def reference_cost_from_sidecar_usage(model: str, usage: SidecarUsage | None) -> float | None:
    """Reference (paid-equivalent) cost for a sidecar request, or None.

    Used to surface savings when the request was served by a free/cheap model:
    the same token usage priced at the resolved paid-equivalent list price.
    """
    if usage is None:
        return None
    return calculate_reference_cost(
        model,
        UsageTokens(
            input_tokens=float(usage.input_tokens),
            output_tokens=float(usage.output_tokens),
            cached_input_tokens=float(usage.cached_input_tokens),
        ),
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

    cost_usd = _float_field(usage, "cost")

    return SidecarUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_tokens,
        cost_usd=cost_usd,
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


def _float_field(payload: Mapping[str, JsonValue], key: str) -> float | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _is_sidecar_context_length_error(exc: ClaudeSidecarError) -> bool:
    if is_json_mapping(exc.body) and is_context_length_error_envelope(exc.body):
        return True
    return is_context_length_error(code=None, message=exc.message)


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
