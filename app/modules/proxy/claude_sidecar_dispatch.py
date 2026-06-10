from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import cast

from fastapi import Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.clients.claude_sidecar import ClaudeSidecarError, ClaudeSidecarUnavailableError, get_claude_sidecar_client
from app.core.config.settings import Settings
from app.core.errors import OpenAIErrorEnvelope, openai_error
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.core.types import JsonObject, JsonValue
from app.core.utils.json_guards import is_json_mapping
from app.core.utils.request_id import get_request_id
from app.core.utils.sse import inject_sse_keepalives
from app.db.session import get_background_session
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyData, ApiKeysService, ApiKeyUsageReservationData
from app.modules.request_logs.repository import RequestLogsRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SidecarUsage:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0


def is_sidecar_model(model: str, settings: Settings) -> bool:
    if not settings.claude_sidecar_enabled:
        return False
    normalized = model.strip().lower()
    return any(normalized.startswith(prefix.strip().lower()) for prefix in settings.claude_sidecar_model_prefixes)


def sidecar_prefix_match(model: str, settings: Settings) -> bool:
    normalized = model.strip().lower()
    return any(normalized.startswith(prefix.strip().lower()) for prefix in settings.claude_sidecar_model_prefixes)


def build_sidecar_chat_payload(payload: ChatCompletionsRequest, effective_model: str) -> dict[str, JsonValue]:
    body = cast(dict[str, JsonValue], payload.model_dump(mode="json", exclude_none=True))
    body["model"] = effective_model
    return body


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
) -> Response:
    body = build_sidecar_chat_payload(payload, effective_model)
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
                ),
                sse_keepalive_interval_seconds,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", **dict(rate_limit_headers)},
        )

    try:
        response_body = await get_claude_sidecar_client().chat_completion(body)
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
) -> AsyncIterator[bytes]:
    usage: SidecarUsage | None = None
    completed = False
    settled = False
    try:
        async with get_claude_sidecar_client().stream_chat_completion(payload) as chunks:
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
