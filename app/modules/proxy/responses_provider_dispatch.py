"""Translate chat-provider Responses traffic and refuse Codex fallthrough.

``/v1/responses`` and ``/backend-api/codex/responses`` share chat's sidecar
routing. Chat completions already dispatch Claude, OpenRouter, OrcaRouter,
Ollama, and OpenAI-compatible endpoints. Responses used to do that only for
OmniRoute and OpenCode Go, so every other provider id was sent to a ChatGPT
Codex account. This module reuses the chat dispatchers and the existing
Responses/chat translators.

Compact and the Codex websocket cannot speak those chat providers. A model
they own must not select a Codex account on those transports. A model that
no sidecar, no model source, and no authoritative Codex catalog serves is
``model_not_found`` rather than a Codex request the upstream will reject.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator, Mapping, Sequence
from typing import cast

from fastapi import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from app.core.clients.claude_sidecar import ClaudeSidecarClient
from app.core.clients.ollama_sidecar import OllamaSidecarClient
from app.core.clients.openai_compat_sidecar import OpenAICompatSidecarClient
from app.core.clients.openrouter_sidecar import OpenRouterSidecarClient
from app.core.clients.orcarouter_sidecar import OrcaRouterSidecarClient
from app.core.clients.proxy import ProxyResponseError
from app.core.errors import OpenAIErrorEnvelope, openai_error
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.core.openai.model_registry import get_model_registry
from app.core.types import JsonObject, JsonValue
from app.core.utils.json_guards import is_json_mapping
from app.core.utils.sse import SSE_DONE, SseJsonDataDecoder, SseJsonEvent, format_sse_data
from app.core.utils.stream_close import ClosingStreamingResponse, aclose_stream
from app.modules.api_keys.service import ApiKeyData, ApiKeyUsageReservationData
from app.modules.openai_compat.endpoints import is_openai_compat_provider
from app.modules.proxy.claude_sidecar_dispatch import proxy_chat_to_sidecar
from app.modules.proxy.ollama_sidecar_dispatch import proxy_chat_to_ollama
from app.modules.proxy.openai_compat_dispatch import proxy_chat_to_openai_compat
from app.modules.proxy.openrouter_sidecar_dispatch import proxy_chat_to_openrouter
from app.modules.proxy.orcarouter_sidecar_dispatch import proxy_chat_to_orcarouter
from app.modules.proxy.request_policy import resolve_model_alias
from app.modules.proxy.responses_chat_bridge import (
    ResponsesStreamSynthesizer,
    chat_to_responses_result,
)
from app.modules.proxy.sidecar_routing import SidecarRoutingEntry, resolve_sidecar_route

_HEADER_HOP_BY_HOP = frozenset({"content-length", "content-type"})
_CHAT_PROVIDERS_ALREADY_ON_RESPONSES = frozenset({"omniroute", "opencode_go"})


def codex_serves_model(model: str) -> bool:
    """Whether a Codex account may be selected for ``model``.

    Before account catalogs are authoritative, absence is not evidence: the
    bootstrap list is a floor, and historical Codex slugs still in use are
    not all on it. Once every active account has reported its catalog, a
    slug that is missing or explicitly withdrawn is not a Codex model.
    """

    registry = get_model_registry()
    snapshot = registry.get_snapshot()
    if snapshot is None or not snapshot.account_catalogs_authoritative or not snapshot.models:
        return True
    canonical = resolve_model_alias(model) or model
    normalized = canonical.strip().lower()
    if not normalized or registry.is_suppressed_model(normalized):
        return False
    return any(slug.strip().lower() == normalized for slug in registry.get_models_with_fallback())


def chat_sidecar_provider(
    model: str,
    entries: tuple[SidecarRoutingEntry, ...],
) -> str | None:
    """Provider key when chat routing owns ``model``, else ``None``."""

    decision = resolve_sidecar_route(model, entries)
    if decision is None:
        return None
    return decision.provider


async def non_http_responses_model_rejection(
    model: str,
    *,
    source_owned: bool,
) -> tuple[int, OpenAIErrorEnvelope] | None:
    """Reject a compact or websocket turn that must not select a Codex account.

    HTTP Responses dispatches sidecar models. Compact and the Codex websocket
    do not. Source-owned models keep the existing HTTP-fallback behavior.
    """

    provider = await _chat_sidecar_provider_for_model(model)
    if provider is not None:
        return (
            400,
            openai_error(
                "model_requires_responses_http",
                f"The model '{model}' is served by a provider that only accepts HTTP /v1/responses.",
                error_type="invalid_request_error",
            ),
        )
    if source_owned or codex_serves_model(model):
        return None
    return (
        404,
        openai_error(
            "model_not_found",
            f"The model '{model}' does not exist",
            error_type="invalid_request_error",
        ),
    )


def raise_for_non_http_responses_rejection(rejection: tuple[int, OpenAIErrorEnvelope]) -> None:
    status_code, payload = rejection
    raise ProxyResponseError(status_code, payload)


async def dispatch_responses_via_chat_provider(
    request: Request,
    chat_request: ChatCompletionsRequest,
    *,
    provider: str,
    effective_model: str,
    wire_model: str | None,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    rate_limit_headers: Mapping[str, str],
    sse_keepalive_interval_seconds: float,
    cursor_compat: bool,
    client: object,
) -> Response:
    """Dispatch one Responses request through the chat provider that owns it.

    ``client`` is built by the caller with the client class bound in
    ``api.py``, so tests that replace those classes observe this path.
    Logging, quota settlement, and error mapping stay inside the chat
    dispatcher. Only a successful chat completion is rewritten into the
    Responses shape.
    """

    if provider in _CHAT_PROVIDERS_ALREADY_ON_RESPONSES:
        raise RuntimeError(f"{provider} Responses traffic has its own dispatcher")
    chat_response = await _proxy_chat(
        request,
        chat_request,
        provider=provider,
        effective_model=effective_model,
        wire_model=wire_model,
        api_key=api_key,
        reservation=reservation,
        rate_limit_headers=rate_limit_headers,
        sse_keepalive_interval_seconds=sse_keepalive_interval_seconds,
        cursor_compat=cursor_compat,
        client=client,
    )
    return translate_chat_response_to_responses(chat_response, model=effective_model)


def translate_chat_response_to_responses(response: Response, *, model: str) -> Response:
    """Rewrite a chat dispatcher response into Responses output.

    Non-success bodies and error envelopes pass through unchanged, including
    status and headers, so the chat path's error mapping is the one the
    client sees. Streaming chat SSE is synthesized into Responses events.
    """

    if isinstance(response, StreamingResponse):
        settling = response._settling if isinstance(response, ClosingStreamingResponse) else None
        return ClosingStreamingResponse(
            _translate_chat_sse(response.body_iterator, model=model),
            status_code=response.status_code,
            headers=_passthrough_headers(response),
            media_type="text/event-stream",
            settling=settling,
        )
    parsed = _json_body(response)
    if response.status_code == 200 and _is_chat_completion(parsed):
        return JSONResponse(
            content=chat_to_responses_result(parsed, model=model),
            status_code=200,
            headers=_passthrough_headers(response),
        )
    return response


async def _chat_sidecar_provider_for_model(model: str) -> str | None:
    # Imported lazily: this module is loaded while ``api`` is still importing
    # the websocket stack, and ``api`` is the module tests patch.
    from app.modules.proxy.api import _enabled_sidecar_routing_entries

    return chat_sidecar_provider(model, await _enabled_sidecar_routing_entries())


async def _proxy_chat(
    request: Request,
    chat_request: ChatCompletionsRequest,
    *,
    provider: str,
    effective_model: str,
    wire_model: str | None,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    rate_limit_headers: Mapping[str, str],
    sse_keepalive_interval_seconds: float,
    cursor_compat: bool,
    client: object,
) -> Response:
    if provider == "claude":
        return await proxy_chat_to_sidecar(
            request,
            chat_request,
            effective_model=effective_model,
            api_key=api_key,
            reservation=reservation,
            rate_limit_headers=rate_limit_headers,
            sse_keepalive_interval_seconds=sse_keepalive_interval_seconds,
            client=cast(ClaudeSidecarClient, client),
            cursor_compat=cursor_compat,
            wire_model=wire_model,
        )
    if provider == "openrouter":
        return await proxy_chat_to_openrouter(
            request,
            chat_request,
            effective_model=effective_model,
            api_key=api_key,
            reservation=reservation,
            rate_limit_headers=rate_limit_headers,
            sse_keepalive_interval_seconds=sse_keepalive_interval_seconds,
            client=cast(OpenRouterSidecarClient, client),
            cursor_compat=cursor_compat,
            wire_model=wire_model,
        )
    if is_openai_compat_provider(provider):
        return await proxy_chat_to_openai_compat(
            request,
            chat_request,
            effective_model=effective_model,
            api_key=api_key,
            reservation=reservation,
            rate_limit_headers=rate_limit_headers,
            sse_keepalive_interval_seconds=sse_keepalive_interval_seconds,
            client=cast(OpenAICompatSidecarClient, client),
            cursor_compat=cursor_compat,
            wire_model=wire_model,
        )
    if provider == "orcarouter":
        return await proxy_chat_to_orcarouter(
            request,
            chat_request,
            effective_model=effective_model,
            api_key=api_key,
            reservation=reservation,
            rate_limit_headers=rate_limit_headers,
            sse_keepalive_interval_seconds=sse_keepalive_interval_seconds,
            client=cast(OrcaRouterSidecarClient, client),
            cursor_compat=cursor_compat,
            wire_model=wire_model,
        )
    if provider == "ollama":
        return await proxy_chat_to_ollama(
            request,
            chat_request,
            effective_model=effective_model,
            api_key=api_key,
            reservation=reservation,
            rate_limit_headers=rate_limit_headers,
            sse_keepalive_interval_seconds=sse_keepalive_interval_seconds,
            client=cast(OllamaSidecarClient, client),
            cursor_compat=cursor_compat,
            wire_model=wire_model,
        )
    raise RuntimeError(f"no Responses chat dispatcher for provider {provider}")


def _passthrough_headers(response: Response) -> dict[str, str]:
    return {key: value for key, value in response.headers.items() if key.lower() not in _HEADER_HOP_BY_HOP}


def _json_body(response: Response) -> JsonValue | None:
    body = getattr(response, "body", None)
    if not isinstance(body, bytes | str) or not body:
        return None
    text = body.decode("utf-8") if isinstance(body, bytes) else body
    try:
        parsed = cast(JsonValue, json.loads(text))
    except ValueError:
        return None
    return parsed


def _is_chat_completion(body: JsonValue | None) -> bool:
    return is_json_mapping(body) and "choices" in body


async def _translate_chat_sse(chunks: AsyncIterable[object], *, model: str) -> AsyncIterator[bytes]:
    decoder = SseJsonDataDecoder()
    synthesizer = ResponsesStreamSynthesizer(model=model)
    state = _SseTranslateState()
    try:
        async for raw_chunk in chunks:
            chunk = _chunk_bytes(raw_chunk)
            produced = False
            for payload, done in _frames_for_events(decoder.feed(chunk), synthesizer, state):
                produced = True
                yield payload
                if done:
                    return
            if not produced and _is_sse_comment(chunk):
                yield chunk if chunk.endswith(b"\n") else chunk + b"\n"
        if not state.finished:
            for payload, done in _frames_for_events(decoder.flush(), synthesizer, state):
                yield payload
                if done:
                    return
        if not state.finished and not state.saw_error:
            for event in synthesizer.finish(upstream_completed=False):
                yield _responses_sse(event)
            yield b"data: [DONE]\n\n"
        elif not state.finished:
            yield b"data: [DONE]\n\n"
    finally:
        await aclose_stream(chunks)


class _SseTranslateState:
    saw_error: bool = False
    finished: bool = False


def _frames_for_events(
    events: Sequence[SseJsonEvent],
    synthesizer: ResponsesStreamSynthesizer,
    state: _SseTranslateState,
) -> list[tuple[bytes, bool]]:
    frames: list[tuple[bytes, bool]] = []
    for event in events:
        if event == SSE_DONE:
            state.finished = True
            if not state.saw_error:
                for responses_event in synthesizer.feed(event):
                    frames.append((_responses_sse(responses_event), False))
            frames.append((b"data: [DONE]\n\n", True))
            return frames
        if is_json_mapping(event) and "error" in event and "choices" not in event:
            state.saw_error = True
            frames.append((format_sse_data(event).encode("utf-8"), False))
            continue
        if state.saw_error or not is_json_mapping(event):
            continue
        for responses_event in synthesizer.feed(event):
            frames.append((_responses_sse(responses_event), False))
    return frames


def _responses_sse(event: JsonObject) -> bytes:
    return format_sse_data(event).encode("utf-8")


def _chunk_bytes(chunk: object) -> bytes:
    if isinstance(chunk, bytes):
        return chunk
    if isinstance(chunk, str):
        return chunk.encode("utf-8")
    return bytes(cast(bytes, chunk))


def _is_sse_comment(chunk: bytes) -> bool:
    stripped = chunk.strip()
    return bool(stripped) and stripped.startswith(b":")
