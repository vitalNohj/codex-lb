from __future__ import annotations

import asyncio
import codecs
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Mapping
from dataclasses import dataclass
from typing import TypeVar, cast

import anyio
from fastapi import Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.clients.openai_compat_sidecar import (
    OpenAICompatSidecarClient,
    OpenAICompatSidecarConfig,
    OpenAICompatSidecarError,
    OpenAICompatSidecarUnavailableError,
    retain_openai_compat_sidecar_clients,
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
from app.modules.openai_compat.endpoints import (
    decrypt_endpoint_api_key,
    parse_openai_compat_endpoints,
)
from app.modules.proxy.claude_sidecar_dispatch import (
    SidecarUsage,
    ensure_stream_usage_requested,
    extract_billed_cost,
    extract_usage,
    reference_cost_from_sidecar_usage,
)
from app.modules.proxy.cursor_chat_compat import (
    apply_cursor_usage_fallback_to_response,
    cursor_context_limit_usage_completion,
    is_sidecar_context_length_error,
    stream_bytes_with_cursor_usage_fallback,
)
from app.modules.proxy.deepseek_v4_compat import (
    capture_non_streaming as deepseek_capture_non_streaming,
)
from app.modules.proxy.deepseek_v4_compat import (
    observe_stream as deepseek_observe_stream,
)
from app.modules.proxy.deepseek_v4_compat import (
    resolve_scope as deepseek_resolve_scope,
)
from app.modules.proxy.external_pricing_logging import (
    BilledCostAccumulator,
    ExternalRequestCost,
    ExternalResponseSettlement,
    cost_microdollars,
    external_request_cost,
    external_response_settlement,
    usage_tokens_from_sidecar,
)
from app.modules.proxy.sidecar_model_profiles import read_reasoning_effort, set_reasoning_effort_override
from app.modules.proxy.sidecar_routing import SidecarRoutingEntry
from app.modules.proxy.sidecar_upstream_errors import (
    call_with_sidecar_provider_retry,
    client_facing_sidecar_error,
    log_sidecar_provider_retry,
    retry_sidecar_provider_failure,
)
from app.modules.request_logs.repository import RequestLogsRepository

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

#: An SSE event ends at two consecutive line endings, in any combination of the
#: three the spec permits. Mirrors ``_SSE_LINE_BOUNDARY`` in
#: ``app/core/utils/sse.py``, applied twice.
_SSE_EVENT_BOUNDARY = re.compile(r"(?:\r\n|\r|\n){2}")


@dataclass(frozen=True, slots=True)
class OpenAICompatChatPayload:
    body: dict[str, JsonValue]
    requested_reasoning_effort: str | None = None
    effective_reasoning_effort: str | None = None


def openai_compat_routing_entry(config: OpenAICompatSidecarConfig) -> SidecarRoutingEntry:
    return SidecarRoutingEntry(
        provider=config.provider_id,
        prefixes=config.prefixes,
        full_models=config.full_models,
    )


async def load_openai_compat_configs() -> tuple[OpenAICompatSidecarConfig, ...]:
    try:
        dashboard_settings = await get_settings_cache().get()
    except Exception:
        logger.warning("failed to load dashboard settings for OpenAI-compat endpoints", exc_info=True)
        return ()
    return openai_compat_configs_from_settings(dashboard_settings)


def openai_compat_configs_from_settings(settings: DashboardSettings) -> tuple[OpenAICompatSidecarConfig, ...]:
    encryptor = TokenEncryptor()
    endpoints = parse_openai_compat_endpoints(settings.openai_compat_endpoints_json)
    # Every read of the endpoint list is also the moment we learn which
    # endpoints still exist, so reconcile the client cache here. Without it a
    # deleted endpoint's cached client - holding its decrypted API key - would
    # survive for the life of the process, since deletion produces no config to
    # evict the entry with.
    retain_openai_compat_sidecar_clients([endpoint.id for endpoint in endpoints])
    configs: list[OpenAICompatSidecarConfig] = []
    for endpoint in endpoints:
        configs.append(
            OpenAICompatSidecarConfig(
                endpoint_id=endpoint.id,
                name=endpoint.name,
                enabled=endpoint.enabled,
                base_url=endpoint.base_url.rstrip("/"),
                api_key=decrypt_endpoint_api_key(endpoint, encryptor),
                prefixes=endpoint.prefixes,
                connect_timeout_seconds=endpoint.connect_timeout_seconds,
                request_timeout_seconds=endpoint.request_timeout_seconds,
                models_cache_ttl_seconds=endpoint.models_cache_ttl_seconds,
                full_models=endpoint.full_models,
                default_reasoning_effort=endpoint.default_reasoning_effort,
            )
        )
    return tuple(configs)


def openai_compat_config_by_provider(
    configs: tuple[OpenAICompatSidecarConfig, ...],
    provider: str,
) -> OpenAICompatSidecarConfig | None:
    for config in configs:
        if config.provider_id == provider:
            return config
    return None


def enabled_openai_compat_routing_entries(
    configs: tuple[OpenAICompatSidecarConfig, ...],
) -> list[SidecarRoutingEntry]:
    return [openai_compat_routing_entry(config) for config in configs if config.enabled]


def build_openai_compat_chat_payload(
    payload: ChatCompletionsRequest,
    effective_model: str,
    config: OpenAICompatSidecarConfig,
) -> OpenAICompatChatPayload:
    body = cast(dict[str, JsonValue], payload.model_dump(mode="json", exclude_none=True))
    requested_reasoning_effort = read_reasoning_effort(body)
    # ``effective_model`` is the wire model already resolved (and stripped per
    # the matched prefix's flag) by the unified resolver.
    body["model"] = effective_model.strip()
    set_reasoning_effort_override(body, config.default_reasoning_effort)
    return OpenAICompatChatPayload(
        body=body,
        requested_reasoning_effort=requested_reasoning_effort,
        effective_reasoning_effort=read_reasoning_effort(body),
    )


async def proxy_chat_to_openai_compat(
    request: Request,
    payload: ChatCompletionsRequest,
    *,
    effective_model: str,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    rate_limit_headers: Mapping[str, str],
    sse_keepalive_interval_seconds: float,
    client: OpenAICompatSidecarClient,
    cursor_compat: bool = False,
    wire_model: str | None = None,
) -> Response:
    sidecar_payload = build_openai_compat_chat_payload(payload, wire_model or effective_model, client.config)
    provider_id = client.config.provider_id
    endpoint_name = client.config.name
    deepseek_scope = deepseek_resolve_scope(
        effective_model=effective_model,
        provider=provider_id,
        sidecar_body=sidecar_payload.body,
        api_key_id=api_key.id if api_key else None,
    )
    requested_at = time.monotonic()
    if payload.stream:
        ensure_stream_usage_requested(sidecar_payload.body)
        stream: AsyncIterator[bytes] = _openai_compat_stream_iterator(
            sidecar_payload.body,
            api_key=api_key,
            reservation=reservation,
            model=effective_model,
            started_at=requested_at,
            client=client,
            reasoning_effort=sidecar_payload.effective_reasoning_effort,
            requested_reasoning_effort=sidecar_payload.requested_reasoning_effort,
        )
        if deepseek_scope is not None:
            stream = deepseek_observe_stream(deepseek_scope, stream)
        if cursor_compat:
            stream = stream_bytes_with_cursor_usage_fallback(
                stream,
                payload,
                source="openai_compat_stream",
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
        response_body = await call_with_sidecar_provider_retry(
            lambda: client.chat_completion(sidecar_payload.body),
            provider=endpoint_name,
            model=effective_model,
        )
    except OpenAICompatSidecarUnavailableError:
        await _release_openai_compat_reservation(reservation, api_key=api_key)
        await _log_openai_compat_request(
            api_key=api_key,
            model=effective_model,
            started_at=requested_at,
            status="error",
            error_code="openai_compat_unavailable",
            error_message=f"{endpoint_name} unavailable",
            reasoning_effort=sidecar_payload.effective_reasoning_effort,
            requested_reasoning_effort=sidecar_payload.requested_reasoning_effort,
            client=client,
        )
        return JSONResponse(
            status_code=503,
            content=openai_error(
                "openai_compat_unavailable",
                f"{endpoint_name} unavailable",
                error_type="upstream_error",
            ),
            headers=dict(rate_limit_headers),
        )
    except OpenAICompatSidecarError as exc:
        # A cursor-compat context-length response is turned into a synthetic
        # SUCCESS for the client, so it must not fall through to the error
        # settlement below: that would log it as an error and finalize a
        # reservation the client was never charged for.
        if cursor_compat and is_sidecar_context_length_error(body=exc.body, message=exc.message):
            await _release_openai_compat_reservation(reservation, api_key=api_key)
            return cursor_context_limit_usage_completion(payload, headers=dict(rate_limit_headers))
        settlement = await external_response_settlement(
            provider=provider_id,
            model=effective_model,
            usage=extract_usage(exc.body),
            billed_cost_usd=extract_billed_cost(exc.body),
            completed=False,
        )
        await _finalize_or_release_openai_compat_reservation(
            reservation,
            api_key=api_key,
            model=effective_model,
            usage=settlement.usage,
            cost=settlement.cost,
        )
        await _log_openai_compat_request(
            api_key=api_key,
            model=effective_model,
            started_at=requested_at,
            status="error",
            error_code="openai_compat_error",
            error_message=exc.message,
            usage=settlement.usage,
            reasoning_effort=sidecar_payload.effective_reasoning_effort,
            requested_reasoning_effort=sidecar_payload.requested_reasoning_effort,
            cost=settlement.cost,
            client=client,
        )
        client_error = client_facing_sidecar_error(
            status_code=exc.status_code,
            message=exc.message,
            error_code="openai_compat_error",
            body=exc.body,
            extra_headers=rate_limit_headers,
        )
        return JSONResponse(
            status_code=client_error.status_code,
            content=client_error.content,
            headers=client_error.headers,
        )

    usage = extract_usage(response_body)
    billed_cost_usd = extract_billed_cost(response_body)
    cost = await _openai_compat_request_cost(
        effective_model, usage, billed_cost_usd=billed_cost_usd, provider=provider_id
    )
    await _finalize_or_release_openai_compat_reservation(
        reservation,
        api_key=api_key,
        model=effective_model,
        usage=usage,
        cost=cost,
    )
    await _log_openai_compat_request(
        api_key=api_key,
        model=effective_model,
        started_at=requested_at,
        status="success",
        usage=usage,
        reasoning_effort=sidecar_payload.effective_reasoning_effort,
        requested_reasoning_effort=sidecar_payload.requested_reasoning_effort,
        cost=cost,
        client=client,
    )
    if deepseek_scope is not None:
        deepseek_capture_non_streaming(deepseek_scope, response_body)
    if cursor_compat and is_json_mapping(response_body):
        response_body = apply_cursor_usage_fallback_to_response(
            cast(dict[str, JsonValue], response_body),
            payload,
            source="openai_compat_non_stream",
        )
    return JSONResponse(content=response_body, status_code=200, headers=dict(rate_limit_headers))


async def _openai_compat_stream_iterator(
    payload: Mapping[str, JsonValue],
    *,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    model: str,
    started_at: float,
    client: OpenAICompatSidecarClient,
    reasoning_effort: str | None = None,
    requested_reasoning_effort: str | None = None,
) -> AsyncIterator[bytes]:
    usage: SidecarUsage | None = None
    billed_cost = BilledCostAccumulator()
    completed = False
    stream_error = False
    error_code = "openai_compat_stream_incomplete"
    error_message: str | None = None
    endpoint_name = client.config.name
    delivered = False
    try:
        for attempt in range(2):
            usage = None
            billed_cost = BilledCostAccumulator()
            completed = False
            stream_error = False
            try:
                async with client.stream_chat_completion(payload) as chunks:
                    decoder = _SseUsageDecoder()
                    async for raw_chunk in chunks:
                        for event in decoder.feed(raw_chunk):
                            if event == "[DONE]":
                                if not stream_error:
                                    completed = True
                                continue
                            provider_error = _sse_provider_error(
                                event,
                                default_code="openai_compat_error",
                                default_message=f"{endpoint_name} stream error",
                            )
                            if provider_error is not None:
                                stream_error = True
                                completed = False
                                error_code, error_message = provider_error
                            event_usage = extract_usage(event)
                            if event_usage is not None:
                                usage = event_usage
                            billed_cost.observe(extract_billed_cost(event))
                        delivered = True
                        yield raw_chunk
                    for event in decoder.flush():
                        if event == "[DONE]":
                            if not stream_error:
                                completed = True
                            continue
                        provider_error = _sse_provider_error(
                            event,
                            default_code="openai_compat_error",
                            default_message=f"{endpoint_name} stream error",
                        )
                        if provider_error is not None:
                            stream_error = True
                            completed = False
                            error_code, error_message = provider_error
                        event_usage = extract_usage(event)
                        if event_usage is not None:
                            usage = event_usage
                        billed_cost.observe(extract_billed_cost(event))
                return
            except OpenAICompatSidecarError as exc:
                if retry_sidecar_provider_failure(attempt=attempt, delivered=delivered, status_code=exc.status_code):
                    log_sidecar_provider_retry(provider=endpoint_name, status_code=exc.status_code, model=model)
                    continue
                if isinstance(exc, OpenAICompatSidecarUnavailableError):
                    error_code = "openai_compat_unavailable"
                    error_message = f"{endpoint_name} unavailable"
                    yield _error_sse(
                        openai_error(
                            "openai_compat_unavailable",
                            f"{endpoint_name} unavailable",
                            error_type="upstream_error",
                        )
                    )
                    yield b"data: [DONE]\n\n"
                    return
                error_code = "openai_compat_error"
                error_message = exc.message
                billed_cost.observe(extract_billed_cost(exc.body))
                client_error = client_facing_sidecar_error(
                    status_code=exc.status_code,
                    message=exc.message,
                    error_code="openai_compat_error",
                    body=exc.body,
                )
                yield _error_sse(client_error.content)
                yield b"data: [DONE]\n\n"
                return
    except BaseException as exc:
        error_code = "openai_compat_stream_interrupted"
        error_message = str(exc) or exc.__class__.__name__
        raise
    finally:
        # Settle as one cancellation-deferred unit, exactly as the OpenRouter
        # sidecar does (see ``openrouter_sidecar_dispatch._settle_stream_
        # deferring_cancellation``). Price resolution is an awaited database
        # read that precedes the reservation write, so a request task cancelled
        # mid-stream raises out of ``external_response_settlement`` before the
        # settlement helper is ever entered - leaving the reservation
        # ``reserved`` and its quota held until stale reclamation.
        #
        # Cancellation is deferred, not swallowed: it is re-raised below, after
        # the request log is written, so the request still terminates as
        # cancelled. The log joins the same deferred unit on purpose -
        # re-raising between the settlement and the log would leave a durable
        # finalized charge with no request-log row explaining it.
        settlement, settlement_deferred_cancellation = await _settle_stream_deferring_cancellation(
            reservation,
            api_key=api_key,
            model=model,
            usage=usage,
            billed_cost_usd=billed_cost.value,
            completed=completed,
            provider=client.config.provider_id,
        )
        _, log_deferred_cancellation = await _await_result_deferring_cancellation(
            _log_openai_compat_request(
                api_key=api_key,
                model=model,
                started_at=started_at,
                status="success" if completed else "error",
                error_code=None if completed else error_code,
                error_message=None if completed else error_message,
                usage=settlement.usage,
                reasoning_effort=reasoning_effort,
                requested_reasoning_effort=requested_reasoning_effort,
                cost=settlement.cost,
                client=client,
            )
        )
        if settlement_deferred_cancellation or log_deferred_cancellation:
            raise asyncio.CancelledError


async def _await_result_deferring_cancellation(awaitable: Awaitable[_T]) -> tuple[_T, bool]:
    """Run ``awaitable`` to completion, deferring cancellation until it finishes.

    Returns ``(result, cancellation_deferred)``. A cancellation delivered while
    the awaitable is in flight is absorbed so the cleanup can finish, and
    reported through the flag so the caller can re-raise it - deferred, never
    swallowed. If the awaitable is itself cancelled, that propagates at once.

    Mirrors the identically named helper in ``openrouter_sidecar_dispatch.py``
    and ``api.py``: settlement that writes durable accounting cannot simply run
    in a ``finally``, because the first ``await`` inside it re-raises the
    pending ``CancelledError`` and work after that point never happens.

    This bounds nothing on its own: callers must pass work that already
    terminates (an owned settlement), never an open-ended wait.
    """

    task = asyncio.ensure_future(awaitable)
    cancellation_deferred = False
    with anyio.CancelScope(shield=True):
        while True:
            try:
                return await asyncio.shield(task), cancellation_deferred
            except asyncio.CancelledError:
                if task.cancelled():
                    raise
                cancellation_deferred = True
    raise RuntimeError("unreachable shielded cancellation-deferral state")


async def _settle_stream_deferring_cancellation(
    reservation: ApiKeyUsageReservationData | None,
    *,
    api_key: ApiKeyData | None,
    model: str,
    usage: SidecarUsage | None,
    billed_cost_usd: float | None,
    completed: bool,
    provider: str,
) -> tuple[ExternalResponseSettlement[SidecarUsage], bool]:
    """Resolve this stream's price and settle its reservation as one unit.

    Kept together deliberately: settlement needs the resolved cost, so splitting
    the two would let a cancelled request settle against a price it never
    resolved. Both steps are the existing ones with the existing captured
    inputs - this changes when they run, not what they decide.
    """

    async def _settle() -> ExternalResponseSettlement[SidecarUsage]:
        settlement = await external_response_settlement(
            provider=provider,
            model=model,
            usage=usage,
            billed_cost_usd=billed_cost_usd,
            completed=completed,
        )
        await _finalize_or_release_openai_compat_reservation(
            reservation,
            api_key=api_key,
            model=model,
            usage=settlement.usage,
            cost=settlement.cost,
        )
        return settlement

    return await _await_result_deferring_cancellation(_settle())


class _SseUsageDecoder:
    """Split an SSE byte stream into events, tolerant of real-world framing.

    This feature routes to *arbitrary* operator-configured OpenAI-compatible
    servers (vLLM, LM Studio, llama.cpp, NIM, ...), so neither property below is
    theoretical. Both mirror the decoder in
    ``app/modules/proxy/opencode_go_sidecar_dispatch.py``.

    * **Event delimiters.** The SSE spec allows ``\\r\\n``, ``\\n`` and bare
      ``\\r`` line endings, so an event boundary is any two consecutive ones.
      Matching only ``\\n\\n`` buffers a CRLF stream to EOF and then parses the
      whole thing as one malformed event - losing the usage object and the
      ``[DONE]`` sentinel, which in turn makes a completed stream log as an
      error and release its reservation instead of finalizing it.

    * **Chunk boundaries are arbitrary byte offsets.** aiohttp splits on the
      network, not on character boundaries, so a multi-byte character can land
      half in one chunk and half in the next. Decoding each chunk independently
      with ``errors="ignore"`` silently deletes those bytes and can corrupt the
      JSON of the event carrying ``usage``.

    Callers therefore feed **bytes**, and this class owns the decoding. The raw
    chunks still reach the client untouched; only this observer decodes.
    """

    def __init__(self) -> None:
        self._buffer = ""
        # One decoder for the whole stream: it is what carries a split
        # multi-byte sequence across the chunk boundary. ``replace`` rather than
        # ``ignore`` so genuinely invalid bytes stay visible as U+FFFD instead of
        # vanishing and silently shortening the text.
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def feed(self, chunk: bytes) -> list[JsonObject | str]:
        self._buffer += self._decoder.decode(chunk)
        return self._drain_complete_events()

    def flush(self) -> list[JsonObject | str]:
        """Drain the tail at EOF, including any undelimited final event.

        Flushing the UTF-8 decoder first matters: a stream truncated mid
        character would otherwise leave those bytes unaccounted for.
        """

        self._buffer += self._decoder.decode(b"", final=True)
        # A well-formed final event may still be followed by a delimiter, so
        # drain complete events before treating the remainder as a partial one.
        events = self._drain_complete_events()
        pending = self._buffer
        self._buffer = ""
        if pending.strip():
            event = _parse_sse_event(pending)
            if event is not None:
                events.append(event)
        return events

    def _drain_complete_events(self) -> list[JsonObject | str]:
        events: list[JsonObject | str] = []
        while True:
            match = _SSE_EVENT_BOUNDARY.search(self._buffer)
            if match is None:
                break
            raw_event = self._buffer[: match.start()]
            self._buffer = self._buffer[match.end() :]
            event = _parse_sse_event(raw_event)
            if event is not None:
                events.append(event)
        return events


def _parse_sse_event(raw_event: str) -> JsonObject | str | None:
    data_lines: list[str] = []
    # ``str.splitlines`` already treats CR, LF and CRLF as line breaks, so a
    # single-line-ending dialect never leaks into field parsing.
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


def _sse_provider_error(
    event: JsonObject | str,
    *,
    default_code: str,
    default_message: str,
) -> tuple[str, str] | None:
    if not is_json_mapping(event):
        return None
    error = event.get("error")
    if error is None:
        return None
    if is_json_mapping(error):
        code = error.get("code")
        message = error.get("message")
        resolved_code = code if isinstance(code, str) and code else default_code
        resolved_message = message if isinstance(message, str) and message else default_message
        return resolved_code, resolved_message
    if isinstance(error, str) and error:
        return default_code, error
    return default_code, default_message


def _error_sse(error: OpenAIErrorEnvelope) -> bytes:
    data = json.dumps(error, ensure_ascii=True, separators=(",", ":"))
    return f"data: {data}\n\n".encode("utf-8")


async def _openai_compat_request_cost(
    model: str,
    usage: SidecarUsage | None,
    *,
    billed_cost_usd: float | None = None,
    provider: str,
) -> ExternalRequestCost:
    """Resolve this request's cost once, for both the quota charge and the log."""

    return await external_request_cost(
        provider=provider,
        model=model,
        usage=usage_tokens_from_sidecar(usage),
        billed_cost_usd=billed_cost_usd if billed_cost_usd is not None else usage.cost_usd if usage else None,
    )


async def _log_openai_compat_request(
    *,
    api_key: ApiKeyData | None,
    model: str,
    started_at: float,
    status: str,
    client: OpenAICompatSidecarClient,
    error_code: str | None = None,
    error_message: str | None = None,
    usage: SidecarUsage | None = None,
    reasoning_effort: str | None = None,
    requested_reasoning_effort: str | None = None,
    cost: ExternalRequestCost | None = None,
) -> None:
    provider_id = client.config.provider_id
    try:
        if cost is None:
            cost = await _openai_compat_request_cost(model, usage, provider=provider_id)
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
                source=provider_id,
                failure_phase="sidecar" if status != "success" else None,
                cost_usd=cost.cost_usd,
                cost_source=cost.cost_source,
                price_status=cost.price_status,
                reference_cost_usd=reference_cost_from_sidecar_usage(
                    model,
                    usage,
                    provider=provider_id,
                ),
            )
    except Exception:
        logger.warning(
            "failed to write OpenAI-compat request log key_id=%s request_id=%s endpoint_id=%s",
            api_key.id if api_key else None,
            get_request_id(),
            client.config.endpoint_id,
            exc_info=True,
        )


async def _finalize_or_release_openai_compat_reservation(
    reservation: ApiKeyUsageReservationData | None,
    *,
    api_key: ApiKeyData | None,
    model: str,
    usage: SidecarUsage | None,
    cost: ExternalRequestCost | None = None,
) -> None:
    """Settle or release one reservation using the caller's resolved cost.

    ``cost`` is whatever the caller already resolved for this request, so the
    quota charge and the log row are the same answer. Settlement resolves nothing
    itself: doing so would read the store a second time inside an open background
    session, and a concurrent lookup landing between the two reads would make the
    two disagree. No cost means nothing is charged.
    """

    if reservation is None:
        return
    try:
        async with get_background_session() as session:
            service = ApiKeysService(ApiKeysRepository(session))
            charge_microdollars = cost_microdollars(cost)
            if usage is None and charge_microdollars == 0:
                await service.release_usage_reservation(reservation.reservation_id)
                return
            await service.finalize_usage_reservation(
                reservation.reservation_id,
                model=model,
                input_tokens=usage.input_tokens if usage is not None else 0,
                output_tokens=usage.output_tokens if usage is not None else 0,
                cached_input_tokens=usage.cached_input_tokens if usage is not None else 0,
                service_tier=None,
                cost_microdollars=charge_microdollars,
            )
    except Exception:
        logger.warning(
            "failed to settle OpenAI-compat API key reservation key_id=%s request_id=%s",
            api_key.id if api_key else None,
            get_request_id(),
            exc_info=True,
        )


async def _release_openai_compat_reservation(
    reservation: ApiKeyUsageReservationData | None,
    *,
    api_key: ApiKeyData | None,
) -> None:
    await _finalize_or_release_openai_compat_reservation(
        reservation,
        api_key=api_key,
        model=reservation.model if reservation else "",
        usage=None,
    )
