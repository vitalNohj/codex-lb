from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Mapping
from typing import cast

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.openai.chat_requests import ChatCompletionsRequest
from app.core.openai.chat_responses import ChatCompletion, ChatCompletionUsage
from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping
from app.modules.api_keys.service import ApiKeyData

logger = logging.getLogger(__name__)

CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS = 1_000_000


def is_cursor_compat_client(request: Request, api_key: ApiKeyData | None) -> bool:
    if api_key is not None and api_key.name.strip().lower() == "cursor":
        return True
    user_agent = request.headers.get("user-agent", "")
    return "cursor" in user_agent.lower()


def is_context_length_error(*, code: str | None, message: str | None) -> bool:
    if code == "context_length_exceeded":
        return True
    if message is None:
        return False
    normalized = message.lower()
    return (
        "context window" in normalized
        or "input token limit exceeded" in normalized
        or "token limit exceeded" in normalized
    )


def is_context_length_error_envelope(payload: JsonValue) -> bool:
    if not is_json_mapping(payload):
        return False
    error = payload.get("error")
    if not is_json_mapping(error):
        return False
    code = error.get("code")
    message = error.get("message")
    return is_context_length_error(
        code=code if isinstance(code, str) else None,
        message=message if isinstance(message, str) else None,
    )


def cursor_context_limit_usage_stream(
    payload: ChatCompletionsRequest,
    *,
    headers: Mapping[str, str] | None = None,
) -> StreamingResponse:
    response_id = f"chatcmpl_{time.time_ns()}"
    created = int(time.time())
    model = payload.model
    usage_tokens = CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS

    def sse_data(data: dict[str, JsonValue] | str) -> str:
        if data == "[DONE]":
            return "data: [DONE]\n\n"
        return f"data: {json.dumps(data, separators=(',', ':'))}\n\n"

    async def body() -> AsyncIterator[str]:
        yield sse_data(
            {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant"},
                        "finish_reason": None,
                    }
                ],
            }
        )
        yield sse_data(
            {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }
                ],
            }
        )
        yield sse_data(
            {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [],
                "usage": {
                    "prompt_tokens": usage_tokens,
                    "completion_tokens": 0,
                    "total_tokens": usage_tokens,
                },
            }
        )
        yield sse_data("[DONE]")

    return StreamingResponse(body(), media_type="text/event-stream", headers=headers)


def cursor_context_limit_usage_completion(
    payload: ChatCompletionsRequest,
    *,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    response_id = f"chatcmpl_{time.time_ns()}"
    created = int(time.time())
    model = payload.model
    usage_tokens = CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS
    return JSONResponse(
        content={
            "id": response_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": ""},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": usage_tokens,
                "completion_tokens": 0,
                "total_tokens": usage_tokens,
            },
        },
        status_code=200,
        headers=headers,
    )


async def stream_with_cursor_usage_fallback(
    stream: AsyncIterator[str],
    payload: ChatCompletionsRequest,
) -> AsyncIterator[str]:
    rewriter = CursorChatSseCompatRewriter(payload, source="stream")
    async for line in stream:
        for chunk in rewriter.feed(line.encode("utf-8")):
            yield chunk.decode("utf-8")
        if rewriter.terminated:
            return
    for chunk in rewriter.flush():
        yield chunk.decode("utf-8")


async def stream_bytes_with_cursor_usage_fallback(
    stream: AsyncIterator[bytes],
    payload: ChatCompletionsRequest,
    *,
    source: str = "stream_bytes",
) -> AsyncIterator[bytes]:
    rewriter = CursorChatSseCompatRewriter(payload, source=source)
    async for chunk in stream:
        for rewritten_chunk in rewriter.feed(chunk):
            yield rewritten_chunk
        if rewriter.terminated:
            return
    for rewritten_chunk in rewriter.flush():
        yield rewritten_chunk


def apply_cursor_usage_fallback(
    result: ChatCompletion,
    payload: ChatCompletionsRequest,
    *,
    source: str,
) -> None:
    usage = result.usage.model_dump(mode="json", exclude_none=True) if result.usage is not None else None
    if not needs_cursor_usage_fallback(usage):
        return
    prompt_tokens = estimate_cursor_prompt_tokens(payload)
    completion_tokens = max(1, estimate_tokens_from_chars(chat_completion_result_chars(result)))
    result.usage = ChatCompletionUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    logger.info(
        "cursor_usage_fallback source=%s model=%s prompt_tokens=%s completion_tokens=%s",
        source,
        payload.model,
        prompt_tokens,
        completion_tokens,
    )


def apply_cursor_usage_fallback_to_response(
    response_body: dict[str, JsonValue],
    payload: ChatCompletionsRequest,
    *,
    source: str,
) -> dict[str, JsonValue]:
    usage = response_body.get("usage")
    if not needs_cursor_usage_fallback(usage):
        return response_body
    prompt_tokens = estimate_cursor_prompt_tokens(payload)
    completion_tokens = max(1, estimate_tokens_from_chars(_response_completion_chars(response_body)))
    response_body["usage"] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    logger.info(
        "cursor_usage_fallback source=%s model=%s prompt_tokens=%s completion_tokens=%s",
        source,
        payload.model,
        prompt_tokens,
        completion_tokens,
    )
    return response_body


class CursorChatSseCompatRewriter:
    def __init__(self, payload: ChatCompletionsRequest, *, source: str = "stream_bytes") -> None:
        self._payload = payload
        self._source = source
        self._prompt_tokens = estimate_cursor_prompt_tokens(payload)
        self._completion_chars = 0
        self._buffer = ""
        self._usage_emitted = False
        self.terminated = False

    def feed(self, chunk: bytes) -> list[bytes]:
        if self.terminated:
            return []
        self._buffer += chunk.decode("utf-8", errors="ignore")
        outputs: list[bytes] = []
        while "\n\n" in self._buffer and not self.terminated:
            raw_event, self._buffer = self._buffer.split("\n\n", 1)
            outputs.extend(self._rewrite_event(raw_event))
        return outputs

    def flush(self) -> list[bytes]:
        if self.terminated or not self._buffer:
            return []
        pending = self._rewrite_event(self._buffer)
        self._buffer = ""
        return pending

    def _rewrite_event(self, raw_event: str) -> list[bytes]:
        data_lines: list[str] = []
        prefix_lines: list[str] = []
        for raw_line in raw_event.splitlines():
            if not raw_line or raw_line.startswith(":"):
                prefix_lines.append(raw_line)
                continue
            field, _, value = raw_line.partition(":")
            if field != "data":
                prefix_lines.append(raw_line)
                continue
            data_lines.append(value[1:] if value.startswith(" ") else value)

        if not data_lines:
            return [_sse_event_bytes(raw_event)]

        data = "\n".join(data_lines)
        if data.strip() == "[DONE]":
            if not self._usage_emitted:
                self._usage_emitted = True
                return [self._build_fallback_usage_chunk(), _sse_event_bytes(raw_event)]
            return [_sse_event_bytes(raw_event)]

        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            return [_sse_event_bytes(raw_event)]

        if not is_json_mapping(parsed):
            return [_sse_event_bytes(raw_event)]

        payload_dict = cast(dict[str, JsonValue], parsed)
        if is_context_length_error_envelope(payload_dict):
            logger.info(
                "cursor_context_limit_fallback source=%s model=%s",
                self._source,
                self._payload.model,
            )
            self.terminated = True
            self._buffer = ""
            return cursor_context_limit_usage_sse_chunks(self._payload)

        self._completion_chars += chat_completion_delta_chars(payload_dict)
        if is_chat_completion_usage_chunk(payload_dict):
            self._usage_emitted = True
            if needs_cursor_usage_fallback(payload_dict.get("usage")):
                completion_tokens = max(1, estimate_tokens_from_chars(self._completion_chars))
                payload_dict["usage"] = {
                    "prompt_tokens": self._prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": self._prompt_tokens + completion_tokens,
                }
                logger.info(
                    "cursor_usage_fallback source=%s model=%s prompt_tokens=%s completion_tokens=%s",
                    self._source,
                    self._payload.model,
                    self._prompt_tokens,
                    completion_tokens,
                )
                rewritten_data = json.dumps(payload_dict, ensure_ascii=True, separators=(",", ":"))
                lines = [*prefix_lines, f"data: {rewritten_data}"]
                return [_sse_event_bytes("\n".join(lines))]

        return [_sse_event_bytes(raw_event)]

    def _build_fallback_usage_chunk(self) -> bytes:
        completion_tokens = max(1, estimate_tokens_from_chars(self._completion_chars))
        payload_dict: dict[str, JsonValue] = {
            "object": "chat.completion.chunk",
            "model": self._payload.model,
            "choices": [],
            "usage": {
                "prompt_tokens": self._prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": self._prompt_tokens + completion_tokens,
            },
        }
        logger.info(
            "cursor_usage_fallback source=%s_synthetic model=%s prompt_tokens=%s completion_tokens=%s",
            self._source,
            self._payload.model,
            self._prompt_tokens,
            completion_tokens,
        )
        rewritten_data = json.dumps(payload_dict, ensure_ascii=True, separators=(",", ":"))
        return f"data: {rewritten_data}\n\n".encode("utf-8")


def _sse_event_bytes(raw_event: str) -> bytes:
    return (raw_event + "\n\n").encode("utf-8")


def is_chat_completion_usage_chunk(payload: dict[str, JsonValue]) -> bool:
    return payload.get("choices") == []


def parse_chat_completion_sse(line: str) -> dict[str, JsonValue] | None:
    stripped = line.strip()
    if not stripped.startswith("data:"):
        return None
    data = stripped.removeprefix("data:").strip()
    if data == "[DONE]":
        return None
    try:
        parsed = json.loads(data)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def needs_cursor_usage_fallback(usage: JsonValue) -> bool:
    if not isinstance(usage, dict):
        return True
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    return not isinstance(prompt_tokens, int) or prompt_tokens <= 0 or not isinstance(completion_tokens, int)


def estimate_cursor_prompt_tokens(payload: ChatCompletionsRequest) -> int:
    data = payload.model_dump(mode="json", exclude_none=True)
    counted: dict[str, JsonValue] = {}
    for key in ("messages", "input", "instructions", "tools", "tool_choice", "response_format"):
        value = data.get(key)
        if value is not None:
            counted[key] = value
    message_count = len(data.get("messages", [])) if isinstance(data.get("messages"), list) else 0
    return max(1, estimate_tokens_from_chars(json_text_chars(counted)) + message_count * 4)


def estimate_tokens_from_chars(chars: int) -> int:
    return (max(0, chars) + 3) // 4


def json_text_chars(value: JsonValue) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(json_text_chars(item) for item in value)
    if isinstance(value, dict):
        return sum(json_text_chars(item) for item in value.values())
    return 0


def chat_completion_delta_chars(payload: dict[str, JsonValue]) -> int:
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return 0
    total = 0
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            continue
        for key in ("content", "refusal"):
            value = delta.get(key)
            if isinstance(value, str):
                total += len(value)
        tool_calls = delta.get("tool_calls")
        if isinstance(tool_calls, list):
            total += json_text_chars(tool_calls)
    return total


def chat_completion_result_chars(result: ChatCompletion) -> int:
    total = 0
    for choice in result.choices:
        message = choice.message
        if isinstance(message.content, str):
            total += len(message.content)
        if isinstance(message.refusal, str):
            total += len(message.refusal)
        if message.tool_calls:
            total += json_text_chars(
                [tool_call.model_dump(mode="json", exclude_none=True) for tool_call in message.tool_calls]
            )
    return total


def cursor_context_limit_usage_sse_chunks(payload: ChatCompletionsRequest) -> list[bytes]:
    response_id = f"chatcmpl_{time.time_ns()}"
    created = int(time.time())
    model = payload.model
    usage_tokens = CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS

    def chunk(data: dict[str, JsonValue] | str) -> bytes:
        if data == "[DONE]":
            return b"data: [DONE]\n\n"
        return f"data: {json.dumps(data, separators=(',', ':'))}\n\n".encode("utf-8")

    return [
        chunk(
            {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant"},
                        "finish_reason": None,
                    }
                ],
            }
        ),
        chunk(
            {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }
                ],
            }
        ),
        chunk(
            {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [],
                "usage": {
                    "prompt_tokens": usage_tokens,
                    "completion_tokens": 0,
                    "total_tokens": usage_tokens,
                },
            }
        ),
        chunk("[DONE]"),
    ]


def _response_completion_chars(response_body: dict[str, JsonValue]) -> int:
    choices = response_body.get("choices")
    if not isinstance(choices, list):
        return 0
    total = 0
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            total += len(content)
        refusal = message.get("refusal")
        if isinstance(refusal, str):
            total += len(refusal)
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            total += json_text_chars(tool_calls)
    return total
