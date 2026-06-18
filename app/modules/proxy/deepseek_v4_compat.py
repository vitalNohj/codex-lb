"""DeepSeek V4 thinking-mode Cursor compatibility.

DeepSeek V4 thinking-mode models reject tool-call continuation turns whose prior
assistant message (the one that emitted ``tool_calls``) does not carry its
``reasoning_content`` back in the request (upstream 400: "reasoning_content in
the thinking mode must be passed back"). Cursor and similar OpenAI-compatible
clients do not echo ``reasoning_content``.

This module repairs the gap on the OpenRouter / OmniRoute sidecar
chat-completions path only, for DeepSeek V4 family models:

1. Capture the assistant ``reasoning_content`` observed on a (non-streaming or
   streaming) response when the assistant turn carries ``tool_calls``.
2. Re-inject the cached reasoning into later outgoing assistant tool-call
   messages for the same logical conversation, provider, model family, and API
   key, before the request leaves the proxy.

The repair mutates only the forwarded sidecar payload; client-visible bytes are
unchanged. Caching is bounded (LRU + TTL) and best-effort: a cache failure must
never break the proxied request.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import cast

from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_list, is_json_mapping

logger = logging.getLogger(__name__)

# Canonical DeepSeek V4 family tokens (lowercased). ``-``/``_`` are treated as
# interchangeable separators when matching.
_FAMILY_TOKENS: tuple[str, ...] = ("deepseek-v4-pro", "deepseek-v4-flash")

_DEFAULT_CACHE_MAXSIZE = 2048
_DEFAULT_CACHE_TTL_SECONDS = 30 * 60.0


def _normalize_token(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def deepseek_v4_family_token(model: str, aliases: frozenset[str] = frozenset()) -> str | None:
    """Return the canonical DeepSeek V4 family token for ``model`` or ``None``.

    Matching is case-insensitive and ``-``/``_`` tolerant. A model matches a
    family token when the normalized model equals an alias, equals the token, or
    contains the token as a path/segment component (so provider-prefixed and
    ``-free``-suffixed forms such as ``oc/deepseek-v4-flash-free`` match).
    """

    normalized = _normalize_token(model)
    if not normalized:
        return None
    # Family-token detection first so an alias that embeds a canonical token
    # (e.g. an alias for ``deepseek-v4-flash``) keys by the canonical family.
    for token in _FAMILY_TOKENS:
        if normalized == token or _contains_segment(normalized, token):
            return token
    if aliases and normalized in {_normalize_token(alias) for alias in aliases}:
        # Alias that does not embed a family token: key it by its own value.
        return normalized
    return None


def _contains_segment(normalized_model: str, token: str) -> bool:
    """True when ``token`` appears as a component of ``normalized_model``.

    Components are delimited by ``/`` and ``-`` boundaries; we accept the token
    when it is bounded by start/end or a ``/`` on the left and start/end or a
    ``/``/``-`` continuation on the right (covering ``-free`` suffixes).
    """

    idx = normalized_model.find(token)
    while idx != -1:
        left_ok = idx == 0 or normalized_model[idx - 1] in "/-"
        right_index = idx + len(token)
        right_ok = right_index == len(normalized_model) or normalized_model[right_index] in "/-"
        if left_ok and right_ok:
            return True
        idx = normalized_model.find(token, idx + 1)
    return False


def is_deepseek_v4_model(model: str, aliases: frozenset[str] = frozenset()) -> bool:
    return deepseek_v4_family_token(model, aliases) is not None


def api_key_hash(api_key_id: str | None) -> str:
    raw = "anon" if api_key_id is None else f"key:{api_key_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Canonical conversation prefix + cache key
# ---------------------------------------------------------------------------


def _reduce_content(content: JsonValue) -> JsonValue:
    """Normalize message ``content`` to a stable, reasoning-free form."""

    if content is None or isinstance(content, str):
        return content
    if is_json_list(content):
        parts: list[JsonValue] = []
        for part in content:
            if is_json_mapping(part):
                part_type = part.get("type")
                text = part.get("text")
                parts.append({"type": part_type, "text": text})
            else:
                parts.append(part)
        return parts
    if is_json_mapping(content):
        return {"type": content.get("type"), "text": content.get("text")}
    return content


def _reduce_tool_calls(tool_calls: JsonValue) -> list[JsonValue]:
    reduced: list[JsonValue] = []
    if not is_json_list(tool_calls):
        return reduced
    for call in tool_calls:
        if not is_json_mapping(call):
            continue
        function = call.get("function")
        name = function.get("name") if is_json_mapping(function) else None
        arguments = function.get("arguments") if is_json_mapping(function) else None
        reduced.append({"id": call.get("id"), "name": name, "arguments": arguments})
    return reduced


def _reduce_message(message: JsonValue) -> JsonValue:
    """Reduce a chat message to a stable view that excludes ``reasoning_content``."""

    if not is_json_mapping(message):
        return message
    role = message.get("role")
    reduced: dict[str, JsonValue] = {"role": role}
    if role == "tool":
        reduced["tool_call_id"] = (
            message.get("tool_call_id") or message.get("toolCallId") or message.get("call_id")
        )
        reduced["content"] = _reduce_content(message.get("content"))
        return reduced
    reduced["content"] = _reduce_content(message.get("content"))
    tool_calls = message.get("tool_calls")
    if is_json_list(tool_calls):
        reduced["tool_calls"] = _reduce_tool_calls(tool_calls)
    return reduced


def canonical_prefix(messages: list[JsonValue]) -> str:
    reduced = [_reduce_message(message) for message in messages]
    return json.dumps(reduced, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def reasoning_cache_key(
    *,
    messages: list[JsonValue],
    provider: str,
    model_family: str,
    api_key_digest: str,
) -> str:
    payload = "\u0000".join(
        (canonical_prefix(messages), provider, model_family, api_key_digest)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Bounded reasoning cache
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Entry:
    reasoning: str
    expires_at: float


class DeepSeekReasoningCache:
    """In-process LRU + TTL cache mapping conversation prefixes to reasoning."""

    def __init__(
        self,
        *,
        maxsize: int = _DEFAULT_CACHE_MAXSIZE,
        ttl_seconds: float = _DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        self._maxsize = maxsize
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._store: OrderedDict[str, _Entry] = OrderedDict()

    def get(self, key: str) -> str | None:
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return entry.reasoning

    def set(self, key: str, reasoning: str) -> None:
        if not reasoning:
            return
        now = time.monotonic()
        with self._lock:
            self._store[key] = _Entry(reasoning=reasoning, expires_at=now + self._ttl)
            self._store.move_to_end(key)
            while len(self._store) > self._maxsize:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


_GLOBAL_CACHE = DeepSeekReasoningCache()


def get_reasoning_cache() -> DeepSeekReasoningCache:
    return _GLOBAL_CACHE


# ---------------------------------------------------------------------------
# Request re-injection (outgoing)
# ---------------------------------------------------------------------------


def _has_nonempty_reasoning(message: JsonValue) -> bool:
    if not is_json_mapping(message):
        return False
    reasoning = message.get("reasoning_content")
    return isinstance(reasoning, str) and bool(reasoning)


def _message_has_tool_calls(message: JsonValue) -> bool:
    return is_json_mapping(message) and is_json_list(message.get("tool_calls"))


def reinject_reasoning_into_sidecar_body(
    body: dict[str, JsonValue],
    *,
    provider: str,
    model_family: str,
    api_key_digest: str,
    cache: DeepSeekReasoningCache,
) -> None:
    """Patch missing ``reasoning_content`` on assistant tool-call messages.

    Mutates ``body`` in place. Best-effort: any failure is swallowed so the
    request is forwarded unchanged.
    """

    try:
        messages = body.get("messages")
        if not is_json_list(messages):
            return
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                continue
            message_dict = cast("dict[str, JsonValue]", message)
            if not _message_has_tool_calls(message_dict) or _has_nonempty_reasoning(message_dict):
                continue
            prefix = list(messages[: index + 1])
            key = reasoning_cache_key(
                messages=prefix,
                provider=provider,
                model_family=model_family,
                api_key_digest=api_key_digest,
            )
            cached = cache.get(key)
            if cached:
                message_dict["reasoning_content"] = cached
    except Exception:
        logger.warning("deepseek_v4 reinject failed provider=%s", provider, exc_info=True)


# ---------------------------------------------------------------------------
# Non-streaming capture
# ---------------------------------------------------------------------------


def capture_reasoning_from_response(
    response_body: JsonValue,
    *,
    outgoing_messages: list[JsonValue],
    provider: str,
    model_family: str,
    api_key_digest: str,
    cache: DeepSeekReasoningCache,
) -> None:
    """Store assistant ``reasoning_content`` from a non-streaming response.

    Stored only when the response assistant message carries ``tool_calls``. The
    cache key is derived from the outgoing conversation prefix plus the new
    assistant tool-call turn synthesized from the response.
    """

    try:
        if not is_json_mapping(response_body):
            return
        choices = response_body.get("choices")
        if not is_json_list(choices) or not choices:
            return
        message = choices[0].get("message") if is_json_mapping(choices[0]) else None
        if not is_json_mapping(message):
            return
        reasoning = message.get("reasoning_content")
        tool_calls = message.get("tool_calls")
        if not isinstance(reasoning, str) or not reasoning:
            return
        if not is_json_list(tool_calls) or not tool_calls:
            return
        assistant_turn: dict[str, JsonValue] = {
            "role": "assistant",
            "content": message.get("content"),
            "tool_calls": tool_calls,
        }
        prefix = [*outgoing_messages, assistant_turn]
        key = reasoning_cache_key(
            messages=prefix,
            provider=provider,
            model_family=model_family,
            api_key_digest=api_key_digest,
        )
        cache.set(key, reasoning)
    except Exception:
        logger.warning("deepseek_v4 non-stream capture failed provider=%s", provider, exc_info=True)


# ---------------------------------------------------------------------------
# Streaming capture
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _PartialToolCall:
    call_id: str | None = None
    call_type: str = "function"
    name: str | None = None
    arguments: str = ""

    def to_json(self) -> JsonValue:
        return {
            "id": self.call_id,
            "type": self.call_type,
            "function": {"name": self.name, "arguments": self.arguments},
        }


class _ToolCallAccumulator:
    """Accumulate streamed tool_call deltas into ordered tool_call objects."""

    def __init__(self) -> None:
        self._by_index: dict[int, _PartialToolCall] = {}

    def feed(self, tool_calls: JsonValue) -> None:
        if not is_json_list(tool_calls):
            return
        for delta in tool_calls:
            if not is_json_mapping(delta):
                continue
            index = delta.get("index")
            idx = index if isinstance(index, int) else len(self._by_index)
            current = self._by_index.setdefault(idx, _PartialToolCall())
            call_id = delta.get("id")
            if isinstance(call_id, str) and call_id:
                current.call_id = call_id
            call_type = delta.get("type")
            if isinstance(call_type, str):
                current.call_type = call_type
            function = delta.get("function")
            if is_json_mapping(function):
                name = function.get("name")
                if isinstance(name, str) and name:
                    current.name = name
                args = function.get("arguments")
                if isinstance(args, str):
                    current.arguments += args

    def build(self) -> list[JsonValue]:
        return [self._by_index[i].to_json() for i in sorted(self._by_index)]

    def has_calls(self) -> bool:
        return bool(self._by_index)


class DeepSeekReasoningStreamObserver:
    """Wrap a sidecar byte stream, observing reasoning without altering bytes.

    All chunks are yielded through unchanged. Reasoning is committed to the
    cache only on a clean tool-call completion (``finish_reason == "tool_calls"``
    followed by ``data: [DONE]``).
    """

    def __init__(
        self,
        stream: AsyncIterator[bytes],
        *,
        outgoing_messages: list[JsonValue],
        provider: str,
        model_family: str,
        api_key_digest: str,
        cache: DeepSeekReasoningCache,
    ) -> None:
        self._stream = stream
        self._recorder = DeepSeekReasoningRecorder(
            outgoing_messages=outgoing_messages,
            provider=provider,
            model_family=model_family,
            api_key_digest=api_key_digest,
            cache=cache,
        )

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self._stream:
                self._recorder.record(chunk)
                yield chunk
        finally:
            self._recorder.commit()


class DeepSeekReasoningRecorder:
    """Accumulate streamed reasoning from SSE byte chunks and commit on success.

    Decoupled from byte forwarding so it can observe either the forwarded
    stream (OmniRoute/OpenRouter) or the *raw* upstream chunks before any
    provider-specific rewriting (CLIProxyAPI tool-name reversal).
    """

    def __init__(
        self,
        *,
        outgoing_messages: list[JsonValue],
        provider: str,
        model_family: str,
        api_key_digest: str,
        cache: DeepSeekReasoningCache,
    ) -> None:
        self._outgoing_messages = outgoing_messages
        self._provider = provider
        self._model_family = model_family
        self._api_key_digest = api_key_digest
        self._cache = cache
        self._buffer = ""
        self._reasoning_parts: list[str] = []
        self._content_parts: list[str] = []
        self._tool_calls = _ToolCallAccumulator()
        self._tool_call_finish = False
        self._done = False
        self._committed = False

    def record(self, chunk: bytes) -> None:
        try:
            self._buffer += chunk.decode("utf-8", errors="ignore")
            while "\n\n" in self._buffer:
                raw_event, self._buffer = self._buffer.split("\n\n", 1)
                self._observe_event(raw_event)
        except Exception:
            logger.debug("deepseek_v4 stream observe error", exc_info=True)

    def _observe_event(self, raw_event: str) -> None:
        data_lines: list[str] = []
        for raw_line in raw_event.splitlines():
            if not raw_line or raw_line.startswith(":"):
                continue
            field, _, value = raw_line.partition(":")
            if field != "data":
                continue
            data_lines.append(value[1:] if value.startswith(" ") else value)
        if not data_lines:
            return
        data = "\n".join(data_lines)
        if data.strip() == "[DONE]":
            self._done = True
            return
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            return
        if not is_json_mapping(parsed):
            return
        choices = parsed.get("choices")
        if not is_json_list(choices):
            return
        for choice in choices:
            if not is_json_mapping(choice):
                continue
            delta = choice.get("delta")
            if is_json_mapping(delta):
                reasoning = delta.get("reasoning_content")
                if isinstance(reasoning, str):
                    self._reasoning_parts.append(reasoning)
                content = delta.get("content")
                if isinstance(content, str):
                    self._content_parts.append(content)
                self._tool_calls.feed(delta.get("tool_calls"))
            if choice.get("finish_reason") == "tool_calls":
                self._tool_call_finish = True

    def commit(self) -> None:
        if self._committed:
            return
        self._committed = True
        if not (self._done and self._tool_call_finish):
            return
        reasoning = "".join(self._reasoning_parts)
        if not reasoning or not self._tool_calls.has_calls():
            return
        try:
            assistant_turn: dict[str, JsonValue] = {
                "role": "assistant",
                "content": "".join(self._content_parts) or None,
                "tool_calls": self._tool_calls.build(),
            }
            prefix = [*self._outgoing_messages, assistant_turn]
            key = reasoning_cache_key(
                messages=prefix,
                provider=self._provider,
                model_family=self._model_family,
                api_key_digest=self._api_key_digest,
            )
            self._cache.set(key, reasoning)
        except Exception:
            logger.warning("deepseek_v4 stream capture failed provider=%s", self._provider, exc_info=True)


# ---------------------------------------------------------------------------
# Dispatch integration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeepSeekScope:
    """Resolved DeepSeek V4 repair scope for one sidecar request."""

    provider: str
    model_family: str
    api_key_digest: str
    outgoing_messages: list[JsonValue]


def resolve_scope(
    *,
    effective_model: str,
    provider: str,
    sidecar_body: dict[str, JsonValue],
    api_key_id: str | None,
    aliases: frozenset[str] = frozenset(),
) -> DeepSeekScope | None:
    """Return a repair scope when the request targets a DeepSeek V4 model.

    ``sidecar_body`` is the already-built sidecar payload; this function also
    re-injects cached reasoning into it in place. Returns ``None`` (and leaves
    the body untouched) for non-DeepSeek traffic.
    """

    family = deepseek_v4_family_token(effective_model, aliases)
    if family is None:
        return None
    digest = api_key_hash(api_key_id)
    messages = sidecar_body.get("messages")
    outgoing: list[JsonValue] = []
    if is_json_list(messages):
        outgoing = [dict(m) for m in messages if is_json_mapping(m)]
    reinject_reasoning_into_sidecar_body(
        sidecar_body,
        provider=provider,
        model_family=family,
        api_key_digest=digest,
        cache=get_reasoning_cache(),
    )
    return DeepSeekScope(
        provider=provider,
        model_family=family,
        api_key_digest=digest,
        outgoing_messages=outgoing,
    )


def capture_non_streaming(scope: DeepSeekScope, response_body: JsonValue) -> None:
    capture_reasoning_from_response(
        response_body,
        outgoing_messages=scope.outgoing_messages,
        provider=scope.provider,
        model_family=scope.model_family,
        api_key_digest=scope.api_key_digest,
        cache=get_reasoning_cache(),
    )


def observe_stream(scope: DeepSeekScope, stream: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    return DeepSeekReasoningStreamObserver(
        stream,
        outgoing_messages=scope.outgoing_messages,
        provider=scope.provider,
        model_family=scope.model_family,
        api_key_digest=scope.api_key_digest,
        cache=get_reasoning_cache(),
    ).__aiter__()


def make_stream_recorder(scope: DeepSeekScope) -> DeepSeekReasoningRecorder:
    """Recorder for observing *raw* upstream SSE chunks inline.

    Used on the CLIProxyAPI path where the forwarded stream rewrites tool
    names; the recorder must see the un-rewritten (forward-sanitized) names so
    its cache key matches the re-injection key.
    """

    return DeepSeekReasoningRecorder(
        outgoing_messages=scope.outgoing_messages,
        provider=scope.provider,
        model_family=scope.model_family,
        api_key_digest=scope.api_key_digest,
        cache=get_reasoning_cache(),
    )
