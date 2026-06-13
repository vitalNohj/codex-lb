from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import cast

from fastapi import Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.clients.omniroute_sidecar import (
    OmniRouteSidecarClient,
    OmniRouteSidecarConfig,
    OmniRouteSidecarError,
    OmniRouteSidecarUnavailableError,
)
from app.core.config.settings_cache import get_settings_cache
from app.core.crypto import TokenEncryptor
from app.core.errors import OpenAIErrorEnvelope, openai_error
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.core.openai.requests import ResponsesRequest
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
)
from app.modules.proxy.cursor_chat_compat import (
    apply_cursor_usage_fallback_to_response,
    stream_bytes_with_cursor_usage_fallback,
)
from app.modules.proxy.omniroute_responses_dispatch import (
    ResponsesStreamSynthesizer,
    omniroute_chat_to_responses_result,
    responses_to_omniroute_chat_request,
)
from app.modules.request_logs.repository import RequestLogsRepository

logger = logging.getLogger(__name__)

OMNIROUTE_SIDECAR_SOURCE = "omniroute_sidecar"


@dataclass(frozen=True, slots=True)
class OmniRouteChatPayload:
    body: dict[str, JsonValue]


def is_omniroute_sidecar_model(model: str, config: OmniRouteSidecarConfig) -> bool:
    if not config.enabled:
        return False
    normalized_model = model.strip().lower()
    return any(normalized_model == selected.strip().lower() for selected in config.selected_models)


async def load_omniroute_sidecar_config() -> OmniRouteSidecarConfig | None:
    try:
        dashboard_settings = await get_settings_cache().get()
    except Exception:
        logger.warning("failed to load dashboard settings for OmniRoute sidecar", exc_info=True)
        return None
    return omniroute_sidecar_config_from_settings(dashboard_settings)


def omniroute_sidecar_config_from_settings(settings: DashboardSettings) -> OmniRouteSidecarConfig:
    api_key = _decrypt_omniroute_secret(settings.omniroute_sidecar_api_key_encrypted)
    return OmniRouteSidecarConfig(
        enabled=bool(settings.omniroute_sidecar_enabled),
        base_url=settings.omniroute_sidecar_base_url.rstrip("/"),
        api_key=api_key,
        selected_models=tuple(_parse_omniroute_sidecar_selected_models(settings.omniroute_sidecar_selected_models_json)),
        connect_timeout_seconds=settings.omniroute_sidecar_connect_timeout_seconds,
        request_timeout_seconds=settings.omniroute_sidecar_request_timeout_seconds,
        models_cache_ttl_seconds=settings.omniroute_sidecar_models_cache_ttl_seconds,
    )


def _decrypt_omniroute_secret(encrypted: bytes | None) -> str | None:
    if not encrypted:
        return None
    try:
        return TokenEncryptor().decrypt(encrypted)
    except Exception:
        logger.warning("failed to decrypt OmniRoute sidecar API key", exc_info=True)
        return None


def _parse_omniroute_sidecar_selected_models(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [entry.strip() for entry in parsed if isinstance(entry, str) and entry.strip()]


def build_omniroute_chat_payload(
    payload: ChatCompletionsRequest,
    effective_model: str,
) -> OmniRouteChatPayload:
    body = cast(dict[str, JsonValue], payload.model_dump(mode="json", exclude_none=True))
    body["model"] = effective_model.strip()
    return OmniRouteChatPayload(body=body)


async def proxy_chat_to_omniroute(
    request: Request,
    payload: ChatCompletionsRequest,
    *,
    effective_model: str,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    rate_limit_headers: Mapping[str, str],
    sse_keepalive_interval_seconds: float,
    client: OmniRouteSidecarClient,
    cursor_compat: bool = False,
) -> Response:
    sidecar_payload = build_omniroute_chat_payload(payload, effective_model)
    requested_at = time.monotonic()
    if payload.stream:
        ensure_stream_usage_requested(sidecar_payload.body)
        stream: AsyncIterator[bytes] = _omniroute_stream_iterator(
            sidecar_payload.body,
            api_key=api_key,
            reservation=reservation,
            model=effective_model,
            started_at=requested_at,
            client=client,
        )
        if cursor_compat:
            stream = stream_bytes_with_cursor_usage_fallback(
                stream,
                payload,
                source="omniroute_sidecar_stream",
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
    except OmniRouteSidecarUnavailableError:
        await _release_omniroute_reservation(reservation, api_key=api_key)
        await _log_omniroute_request(
            api_key=api_key,
            model=effective_model,
            started_at=requested_at,
            status="error",
            error_code="omniroute_sidecar_unavailable",
            error_message="OmniRoute sidecar unavailable",
        )
        return JSONResponse(
            status_code=503,
            content=openai_error(
                "omniroute_sidecar_unavailable",
                "OmniRoute sidecar unavailable",
                error_type="upstream_error",
            ),
            headers=dict(rate_limit_headers),
        )
    except OmniRouteSidecarError as exc:
        await _release_omniroute_reservation(reservation, api_key=api_key)
        await _log_omniroute_request(
            api_key=api_key,
            model=effective_model,
            started_at=requested_at,
            status="error",
            error_code="omniroute_sidecar_error",
            error_message=exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_openai_error_content(exc),
            headers=dict(rate_limit_headers),
        )

    usage = extract_usage(response_body)
    await _finalize_or_release_omniroute_reservation(
        reservation,
        api_key=api_key,
        model=effective_model,
        usage=usage,
    )
    await _log_omniroute_request(
        api_key=api_key,
        model=effective_model,
        started_at=requested_at,
        status="success",
        usage=usage,
    )
    if cursor_compat and is_json_mapping(response_body):
        response_body = apply_cursor_usage_fallback_to_response(
            cast(dict[str, JsonValue], response_body),
            payload,
            source="omniroute_sidecar_non_stream",
        )
    return JSONResponse(content=response_body, status_code=200, headers=dict(rate_limit_headers))


async def _omniroute_stream_iterator(
    payload: Mapping[str, JsonValue],
    *,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    model: str,
    started_at: float,
    client: OmniRouteSidecarClient,
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
    except OmniRouteSidecarUnavailableError:
        await _release_omniroute_reservation(reservation, api_key=api_key)
        await _log_omniroute_request(
            api_key=api_key,
            model=model,
            started_at=started_at,
            status="error",
            error_code="omniroute_sidecar_unavailable",
            error_message="OmniRoute sidecar unavailable",
        )
        settled = True
        yield _error_sse(
            openai_error(
                "omniroute_sidecar_unavailable",
                "OmniRoute sidecar unavailable",
                error_type="upstream_error",
            )
        )
        yield b"data: [DONE]\n\n"
    except OmniRouteSidecarError as exc:
        await _release_omniroute_reservation(reservation, api_key=api_key)
        await _log_omniroute_request(
            api_key=api_key,
            model=model,
            started_at=started_at,
            status="error",
            error_code="omniroute_sidecar_error",
            error_message=exc.message,
        )
        settled = True
        yield _error_sse(_openai_error_content(exc))
        yield b"data: [DONE]\n\n"
    except BaseException as exc:
        await _release_omniroute_reservation(reservation, api_key=api_key)
        await _log_omniroute_request(
            api_key=api_key,
            model=model,
            started_at=started_at,
            status="error",
            error_code="omniroute_sidecar_stream_interrupted",
            error_message=str(exc) or exc.__class__.__name__,
        )
        settled = True
        raise
    finally:
        if not settled:
            usage_to_settle = usage if completed else None
            await _finalize_or_release_omniroute_reservation(
                reservation,
                api_key=api_key,
                model=model,
                usage=usage_to_settle,
            )
            await _log_omniroute_request(
                api_key=api_key,
                model=model,
                started_at=started_at,
                status="success" if completed else "error",
                error_code=None if completed else "omniroute_sidecar_stream_incomplete",
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


def _openai_error_content(exc: OmniRouteSidecarError) -> OpenAIErrorEnvelope:
    if is_json_mapping(exc.body):
        error = exc.body.get("error")
        if is_json_mapping(error):
            message = error.get("message")
            if isinstance(message, str) and message:
                return cast(OpenAIErrorEnvelope, exc.body)
    return openai_error("omniroute_sidecar_error", exc.message, error_type="upstream_error")


def _error_sse(error: OpenAIErrorEnvelope) -> bytes:
    data = json.dumps(error, ensure_ascii=True, separators=(",", ":"))
    return f"data: {data}\n\n".encode("utf-8")


async def _log_omniroute_request(
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
                source=OMNIROUTE_SIDECAR_SOURCE,
                failure_phase="sidecar" if status != "success" else None,
            )
    except Exception:
        logger.warning(
            "failed to write OmniRoute sidecar request log key_id=%s request_id=%s",
            api_key.id if api_key else None,
            get_request_id(),
            exc_info=True,
        )


async def _finalize_or_release_omniroute_reservation(
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
            "failed to settle OmniRoute sidecar API key reservation key_id=%s request_id=%s",
            api_key.id if api_key else None,
            get_request_id(),
            exc_info=True,
        )


async def _release_omniroute_reservation(
    reservation: ApiKeyUsageReservationData | None,
    *,
    api_key: ApiKeyData | None,
) -> None:
    await _finalize_or_release_omniroute_reservation(
        reservation,
        api_key=api_key,
        model=reservation.model if reservation else "",
        usage=None,
    )


def _responses_sse(event: JsonObject) -> bytes:
    data = json.dumps(event, ensure_ascii=True, separators=(",", ":"))
    return f"data: {data}\n\n".encode("utf-8")


async def proxy_responses_to_omniroute(
    request: Request,
    payload: ResponsesRequest,
    *,
    effective_model: str,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    rate_limit_headers: Mapping[str, str],
    sse_keepalive_interval_seconds: float,
    client: OmniRouteSidecarClient,
) -> Response:
    """Dispatch a Responses-shaped request to OmniRoute and return Responses output.

    The Responses request is translated into an OmniRoute ``/chat/completions``
    request, and OmniRoute's chat-completions output is translated back into the
    Responses result (non-streaming) or Responses event stream (streaming).
    """

    chat_request = responses_to_omniroute_chat_request(payload, effective_model)
    chat_body = build_omniroute_chat_payload(chat_request, effective_model).body
    requested_at = time.monotonic()
    stream = bool(payload.stream)

    if stream:
        ensure_stream_usage_requested(chat_body)
        return StreamingResponse(
            inject_sse_keepalives(
                _omniroute_responses_stream_iterator(
                    chat_body,
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
        response_body = await client.chat_completion(chat_body)
    except OmniRouteSidecarUnavailableError:
        await _release_omniroute_reservation(reservation, api_key=api_key)
        await _log_omniroute_request(
            api_key=api_key,
            model=effective_model,
            started_at=requested_at,
            status="error",
            error_code="omniroute_sidecar_unavailable",
            error_message="OmniRoute sidecar unavailable",
        )
        return JSONResponse(
            status_code=503,
            content=openai_error(
                "omniroute_sidecar_unavailable",
                "OmniRoute sidecar unavailable",
                error_type="upstream_error",
            ),
            headers=dict(rate_limit_headers),
        )
    except OmniRouteSidecarError as exc:
        await _release_omniroute_reservation(reservation, api_key=api_key)
        await _log_omniroute_request(
            api_key=api_key,
            model=effective_model,
            started_at=requested_at,
            status="error",
            error_code="omniroute_sidecar_error",
            error_message=exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_openai_error_content(exc),
            headers=dict(rate_limit_headers),
        )

    usage = extract_usage(response_body)
    await _finalize_or_release_omniroute_reservation(
        reservation,
        api_key=api_key,
        model=effective_model,
        usage=usage,
    )
    await _log_omniroute_request(
        api_key=api_key,
        model=effective_model,
        started_at=requested_at,
        status="success",
        usage=usage,
    )
    result = omniroute_chat_to_responses_result(response_body, model=effective_model)
    return JSONResponse(content=result, status_code=200, headers=dict(rate_limit_headers))


async def _omniroute_responses_stream_iterator(
    payload: Mapping[str, JsonValue],
    *,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    model: str,
    started_at: float,
    client: OmniRouteSidecarClient,
) -> AsyncIterator[bytes]:
    usage: SidecarUsage | None = None
    completed = False
    settled = False
    synthesizer = ResponsesStreamSynthesizer(model=model)
    try:
        async with client.stream_chat_completion(payload) as chunks:
            decoder = _SseUsageDecoder()
            async for raw_chunk in chunks:
                for event in decoder.feed(raw_chunk.decode("utf-8", errors="ignore")):
                    if event == "[DONE]":
                        completed = True
                    else:
                        event_usage = extract_usage(event)
                        if event_usage is not None:
                            usage = event_usage
                    for responses_event in synthesizer.feed(event):
                        yield _responses_sse(responses_event)
            for event in decoder.flush():
                if event == "[DONE]":
                    completed = True
                else:
                    event_usage = extract_usage(event)
                    if event_usage is not None:
                        usage = event_usage
                for responses_event in synthesizer.feed(event):
                    yield _responses_sse(responses_event)
            for responses_event in synthesizer.finish():
                yield _responses_sse(responses_event)
            yield b"data: [DONE]\n\n"
    except OmniRouteSidecarUnavailableError:
        await _release_omniroute_reservation(reservation, api_key=api_key)
        await _log_omniroute_request(
            api_key=api_key,
            model=model,
            started_at=started_at,
            status="error",
            error_code="omniroute_sidecar_unavailable",
            error_message="OmniRoute sidecar unavailable",
        )
        settled = True
        yield _error_sse(
            openai_error(
                "omniroute_sidecar_unavailable",
                "OmniRoute sidecar unavailable",
                error_type="upstream_error",
            )
        )
        yield b"data: [DONE]\n\n"
    except OmniRouteSidecarError as exc:
        await _release_omniroute_reservation(reservation, api_key=api_key)
        await _log_omniroute_request(
            api_key=api_key,
            model=model,
            started_at=started_at,
            status="error",
            error_code="omniroute_sidecar_error",
            error_message=exc.message,
        )
        settled = True
        yield _error_sse(_openai_error_content(exc))
        yield b"data: [DONE]\n\n"
    except BaseException as exc:
        await _release_omniroute_reservation(reservation, api_key=api_key)
        await _log_omniroute_request(
            api_key=api_key,
            model=model,
            started_at=started_at,
            status="error",
            error_code="omniroute_sidecar_stream_interrupted",
            error_message=str(exc) or exc.__class__.__name__,
        )
        settled = True
        raise
    finally:
        if not settled:
            usage_to_settle = usage if completed else None
            await _finalize_or_release_omniroute_reservation(
                reservation,
                api_key=api_key,
                model=model,
                usage=usage_to_settle,
            )
            await _log_omniroute_request(
                api_key=api_key,
                model=model,
                started_at=started_at,
                status="success" if completed else "error",
                error_code=None if completed else "omniroute_sidecar_stream_incomplete",
                usage=usage_to_settle,
            )
