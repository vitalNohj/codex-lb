from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import cast

from fastapi import Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.clients.openrouter_sidecar import (
    OpenRouterSidecarClient,
    OpenRouterSidecarConfig,
    OpenRouterSidecarError,
    OpenRouterSidecarUnavailableError,
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
from app.modules.proxy.claude_sidecar_dispatch import (
    SidecarUsage,
    ensure_stream_usage_requested,
    extract_usage,
    reference_cost_from_sidecar_usage,
)
from app.modules.proxy.cursor_chat_compat import (
    apply_cursor_usage_fallback_to_response,
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
from app.modules.proxy.sidecar_model_profiles import set_reasoning_effort_override
from app.modules.proxy.sidecar_routing import (
    SidecarRoutingEntry,
    parse_sidecar_full_models,
    parse_sidecar_prefixes,
)
from app.modules.request_logs.repository import RequestLogsRepository

logger = logging.getLogger(__name__)

OPENROUTER_SIDECAR_SOURCE = "openrouter_sidecar"


@dataclass(frozen=True, slots=True)
class OpenRouterChatPayload:
    body: dict[str, JsonValue]


def openrouter_routing_entry(config: OpenRouterSidecarConfig) -> SidecarRoutingEntry:
    return SidecarRoutingEntry(
        provider="openrouter",
        prefixes=config.prefixes,
        full_models=config.full_models,
    )


async def load_openrouter_sidecar_config() -> OpenRouterSidecarConfig | None:
    try:
        dashboard_settings = await get_settings_cache().get()
    except Exception:
        logger.warning("failed to load dashboard settings for OpenRouter sidecar", exc_info=True)
        return None
    return openrouter_sidecar_config_from_settings(dashboard_settings)


def openrouter_sidecar_config_from_settings(settings: DashboardSettings) -> OpenRouterSidecarConfig:
    api_key = _decrypt_openrouter_secret(settings.openrouter_sidecar_api_key_encrypted)
    return OpenRouterSidecarConfig(
        enabled=bool(settings.openrouter_sidecar_enabled),
        base_url=settings.openrouter_sidecar_base_url.rstrip("/"),
        api_key=api_key,
        prefixes=parse_sidecar_prefixes(settings.openrouter_sidecar_model_prefixes_json),
        connect_timeout_seconds=settings.openrouter_sidecar_connect_timeout_seconds,
        request_timeout_seconds=settings.openrouter_sidecar_request_timeout_seconds,
        models_cache_ttl_seconds=settings.openrouter_sidecar_models_cache_ttl_seconds,
        full_models=parse_sidecar_full_models(settings.openrouter_sidecar_full_models_json),
        default_reasoning_effort=settings.openrouter_sidecar_default_reasoning_effort,
    )


def _decrypt_openrouter_secret(encrypted: bytes | None) -> str | None:
    if not encrypted:
        return None
    try:
        return TokenEncryptor().decrypt(encrypted)
    except Exception:
        logger.warning("failed to decrypt OpenRouter sidecar API key", exc_info=True)
        return None


def build_openrouter_chat_payload(
    payload: ChatCompletionsRequest,
    effective_model: str,
    config: OpenRouterSidecarConfig,
) -> OpenRouterChatPayload:
    body = cast(dict[str, JsonValue], payload.model_dump(mode="json", exclude_none=True))
    # ``effective_model`` is the wire model already resolved (and stripped per
    # the matched prefix's flag) by the unified resolver.
    body["model"] = effective_model.strip()
    set_reasoning_effort_override(body, config.default_reasoning_effort)
    return OpenRouterChatPayload(body=body)


async def proxy_chat_to_openrouter(
    request: Request,
    payload: ChatCompletionsRequest,
    *,
    effective_model: str,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    rate_limit_headers: Mapping[str, str],
    sse_keepalive_interval_seconds: float,
    client: OpenRouterSidecarClient,
    cursor_compat: bool = False,
    wire_model: str | None = None,
) -> Response:
    sidecar_payload = build_openrouter_chat_payload(payload, wire_model or effective_model, client.config)
    deepseek_scope = deepseek_resolve_scope(
        effective_model=effective_model,
        provider="openrouter",
        sidecar_body=sidecar_payload.body,
        api_key_id=api_key.id if api_key else None,
    )
    requested_at = time.monotonic()
    if payload.stream:
        ensure_stream_usage_requested(sidecar_payload.body)
        stream: AsyncIterator[bytes] = _openrouter_stream_iterator(
            sidecar_payload.body,
            api_key=api_key,
            reservation=reservation,
            model=effective_model,
            started_at=requested_at,
            client=client,
        )
        if deepseek_scope is not None:
            stream = deepseek_observe_stream(deepseek_scope, stream)
        if cursor_compat:
            stream = stream_bytes_with_cursor_usage_fallback(
                stream,
                payload,
                source="openrouter_sidecar_stream",
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
    except OpenRouterSidecarUnavailableError:
        await _release_openrouter_reservation(reservation, api_key=api_key)
        await _log_openrouter_request(
            api_key=api_key,
            model=effective_model,
            started_at=requested_at,
            status="error",
            error_code="openrouter_sidecar_unavailable",
            error_message="OpenRouter sidecar unavailable",
        )
        return JSONResponse(
            status_code=503,
            content=openai_error(
                "openrouter_sidecar_unavailable",
                "OpenRouter sidecar unavailable",
                error_type="upstream_error",
            ),
            headers=dict(rate_limit_headers),
        )
    except OpenRouterSidecarError as exc:
        await _release_openrouter_reservation(reservation, api_key=api_key)
        await _log_openrouter_request(
            api_key=api_key,
            model=effective_model,
            started_at=requested_at,
            status="error",
            error_code="openrouter_sidecar_error",
            error_message=exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_openai_error_content(exc),
            headers=dict(rate_limit_headers),
        )

    usage = extract_usage(response_body)
    await _finalize_or_release_openrouter_reservation(
        reservation,
        api_key=api_key,
        model=effective_model,
        usage=usage,
    )
    await _log_openrouter_request(
        api_key=api_key,
        model=effective_model,
        started_at=requested_at,
        status="success",
        usage=usage,
    )
    if deepseek_scope is not None:
        deepseek_capture_non_streaming(deepseek_scope, response_body)
    if cursor_compat and is_json_mapping(response_body):
        response_body = apply_cursor_usage_fallback_to_response(
            cast(dict[str, JsonValue], response_body),
            payload,
            source="openrouter_sidecar_non_stream",
        )
    return JSONResponse(content=response_body, status_code=200, headers=dict(rate_limit_headers))


async def _openrouter_stream_iterator(
    payload: Mapping[str, JsonValue],
    *,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    model: str,
    started_at: float,
    client: OpenRouterSidecarClient,
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
    except OpenRouterSidecarUnavailableError:
        await _release_openrouter_reservation(reservation, api_key=api_key)
        await _log_openrouter_request(
            api_key=api_key,
            model=model,
            started_at=started_at,
            status="error",
            error_code="openrouter_sidecar_unavailable",
            error_message="OpenRouter sidecar unavailable",
        )
        settled = True
        yield _error_sse(
            openai_error(
                "openrouter_sidecar_unavailable",
                "OpenRouter sidecar unavailable",
                error_type="upstream_error",
            )
        )
        yield b"data: [DONE]\n\n"
    except OpenRouterSidecarError as exc:
        await _release_openrouter_reservation(reservation, api_key=api_key)
        await _log_openrouter_request(
            api_key=api_key,
            model=model,
            started_at=started_at,
            status="error",
            error_code="openrouter_sidecar_error",
            error_message=exc.message,
        )
        settled = True
        yield _error_sse(_openai_error_content(exc))
        yield b"data: [DONE]\n\n"
    except BaseException as exc:
        await _release_openrouter_reservation(reservation, api_key=api_key)
        await _log_openrouter_request(
            api_key=api_key,
            model=model,
            started_at=started_at,
            status="error",
            error_code="openrouter_sidecar_stream_interrupted",
            error_message=str(exc) or exc.__class__.__name__,
        )
        settled = True
        raise
    finally:
        if not settled:
            usage_to_settle = usage if completed else None
            await _finalize_or_release_openrouter_reservation(
                reservation,
                api_key=api_key,
                model=model,
                usage=usage_to_settle,
            )
            await _log_openrouter_request(
                api_key=api_key,
                model=model,
                started_at=started_at,
                status="success" if completed else "error",
                error_code=None if completed else "openrouter_sidecar_stream_incomplete",
                usage=usage_to_settle,
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


def _openai_error_content(exc: OpenRouterSidecarError) -> OpenAIErrorEnvelope:
    if is_json_mapping(exc.body):
        error = exc.body.get("error")
        if is_json_mapping(error):
            message = error.get("message")
            if isinstance(message, str) and message:
                return cast(OpenAIErrorEnvelope, exc.body)
    return openai_error("openrouter_sidecar_error", exc.message, error_type="upstream_error")


def _error_sse(error: OpenAIErrorEnvelope) -> bytes:
    data = json.dumps(error, ensure_ascii=True, separators=(",", ":"))
    return f"data: {data}\n\n".encode("utf-8")


async def _log_openrouter_request(
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
                source=OPENROUTER_SIDECAR_SOURCE,
                failure_phase="sidecar" if status != "success" else None,
                cost_usd=usage.cost_usd if usage else None,
                reference_cost_usd=reference_cost_from_sidecar_usage(model, usage),
            )
    except Exception:
        logger.warning(
            "failed to write OpenRouter sidecar request log key_id=%s request_id=%s",
            api_key.id if api_key else None,
            get_request_id(),
            exc_info=True,
        )


async def _finalize_or_release_openrouter_reservation(
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
            "failed to settle OpenRouter sidecar API key reservation key_id=%s request_id=%s",
            api_key.id if api_key else None,
            get_request_id(),
            exc_info=True,
        )


async def _release_openrouter_reservation(
    reservation: ApiKeyUsageReservationData | None,
    *,
    api_key: ApiKeyData | None,
) -> None:
    await _finalize_or_release_openrouter_reservation(
        reservation,
        api_key=api_key,
        model=reservation.model if reservation else "",
        usage=None,
    )
