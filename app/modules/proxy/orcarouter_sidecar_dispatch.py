from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import cast

from fastapi import Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.clients.orcarouter_sidecar import (
    ORCAROUTER_PRICING_PROVIDER,
    OrcaRouterSidecarClient,
    OrcaRouterSidecarConfig,
    OrcaRouterSidecarError,
    OrcaRouterSidecarUnavailableError,
    sanitize_orcarouter_error_body,
    sanitize_orcarouter_message,
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
    ExternalRequestCost,
    cost_microdollars,
    external_request_cost,
    usage_tokens_from_sidecar,
)
from app.modules.proxy.sidecar_model_profiles import read_reasoning_effort, set_reasoning_effort_override
from app.modules.proxy.sidecar_routing import (
    SidecarRoutingEntry,
    parse_sidecar_full_models,
    parse_sidecar_prefixes,
)
from app.modules.proxy.sidecar_upstream_errors import client_facing_sidecar_error
from app.modules.request_logs.repository import RequestLogsRepository

logger = logging.getLogger(__name__)

ORCAROUTER_SIDECAR_SOURCE = "orcarouter_sidecar"


@dataclass(frozen=True, slots=True)
class OrcaRouterChatPayload:
    body: dict[str, JsonValue]
    requested_reasoning_effort: str | None = None
    effective_reasoning_effort: str | None = None


def orcarouter_routing_entry(config: OrcaRouterSidecarConfig) -> SidecarRoutingEntry:
    return SidecarRoutingEntry(
        provider="orcarouter",
        prefixes=config.prefixes,
        full_models=config.full_models,
    )


async def load_orcarouter_sidecar_config() -> OrcaRouterSidecarConfig | None:
    try:
        dashboard_settings = await get_settings_cache().get()
    except Exception:
        logger.warning("failed to load dashboard settings for OrcaRouter sidecar", exc_info=True)
        return None
    return orcarouter_sidecar_config_from_settings(dashboard_settings)


def orcarouter_sidecar_config_from_settings(settings: DashboardSettings) -> OrcaRouterSidecarConfig:
    api_key = _decrypt_orcarouter_secret(settings.orcarouter_sidecar_api_key_encrypted)
    return OrcaRouterSidecarConfig(
        enabled=bool(settings.orcarouter_sidecar_enabled),
        base_url=settings.orcarouter_sidecar_base_url.rstrip("/"),
        api_key=api_key,
        prefixes=parse_sidecar_prefixes(settings.orcarouter_sidecar_model_prefixes_json),
        connect_timeout_seconds=settings.orcarouter_sidecar_connect_timeout_seconds,
        request_timeout_seconds=settings.orcarouter_sidecar_request_timeout_seconds,
        models_cache_ttl_seconds=settings.orcarouter_sidecar_models_cache_ttl_seconds,
        full_models=parse_sidecar_full_models(settings.orcarouter_sidecar_full_models_json),
        default_reasoning_effort=settings.orcarouter_sidecar_default_reasoning_effort,
    )


def _decrypt_orcarouter_secret(encrypted: bytes | None) -> str | None:
    if not encrypted:
        return None
    try:
        return TokenEncryptor().decrypt(encrypted)
    except Exception:
        logger.warning("failed to decrypt OrcaRouter sidecar API key", exc_info=True)
        return None


def build_orcarouter_chat_payload(
    payload: ChatCompletionsRequest,
    effective_model: str,
    config: OrcaRouterSidecarConfig,
) -> OrcaRouterChatPayload:
    body = cast(dict[str, JsonValue], payload.model_dump(mode="json", exclude_none=True))
    requested_reasoning_effort = read_reasoning_effort(body)
    # ``effective_model`` is the wire model already resolved (and stripped per
    # the matched prefix's flag) by the unified resolver.
    body["model"] = effective_model.strip()
    set_reasoning_effort_override(body, config.default_reasoning_effort)
    return OrcaRouterChatPayload(
        body=body,
        requested_reasoning_effort=requested_reasoning_effort,
        effective_reasoning_effort=read_reasoning_effort(body),
    )


async def proxy_chat_to_orcarouter(
    request: Request,
    payload: ChatCompletionsRequest,
    *,
    effective_model: str,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    rate_limit_headers: Mapping[str, str],
    sse_keepalive_interval_seconds: float,
    client: OrcaRouterSidecarClient,
    cursor_compat: bool = False,
    wire_model: str | None = None,
) -> Response:
    sidecar_payload = build_orcarouter_chat_payload(payload, wire_model or effective_model, client.config)
    deepseek_scope = deepseek_resolve_scope(
        effective_model=effective_model,
        provider="orcarouter",
        sidecar_body=sidecar_payload.body,
        api_key_id=api_key.id if api_key else None,
    )
    requested_at = time.monotonic()
    if payload.stream:
        ensure_stream_usage_requested(sidecar_payload.body)
        stream: AsyncIterator[bytes] = _orcarouter_stream_iterator(
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
                source="orcarouter_sidecar_stream",
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
    except OrcaRouterSidecarUnavailableError:
        await _release_orcarouter_reservation(reservation, api_key=api_key)
        await _log_orcarouter_request(
            api_key=api_key,
            model=effective_model,
            started_at=requested_at,
            status="error",
            error_code="orcarouter_sidecar_unavailable",
            error_message="OrcaRouter sidecar unavailable",
            reasoning_effort=sidecar_payload.effective_reasoning_effort,
            requested_reasoning_effort=sidecar_payload.requested_reasoning_effort,
        )
        return JSONResponse(
            status_code=503,
            content=openai_error(
                "orcarouter_sidecar_unavailable",
                "OrcaRouter sidecar unavailable",
                error_type="upstream_error",
            ),
            headers=dict(rate_limit_headers),
        )
    except OrcaRouterSidecarError as exc:
        if cursor_compat and is_sidecar_context_length_error(body=exc.body, message=exc.message):
            await _release_orcarouter_reservation(reservation, api_key=api_key)
            return cursor_context_limit_usage_completion(payload, headers=dict(rate_limit_headers))
        await _release_orcarouter_reservation(reservation, api_key=api_key)
        await _log_orcarouter_request(
            api_key=api_key,
            model=effective_model,
            started_at=requested_at,
            status="error",
            error_code="orcarouter_sidecar_error",
            error_message=sanitize_orcarouter_message(exc.message, api_key=client.config.api_key),
            reasoning_effort=sidecar_payload.effective_reasoning_effort,
            requested_reasoning_effort=sidecar_payload.requested_reasoning_effort,
        )
        client_error = client_facing_sidecar_error(
            status_code=exc.status_code,
            message=sanitize_orcarouter_message(exc.message, api_key=client.config.api_key),
            error_code="orcarouter_sidecar_error",
            body=sanitize_orcarouter_error_body(exc.body, api_key=client.config.api_key),
            extra_headers=rate_limit_headers,
        )
        return JSONResponse(
            status_code=client_error.status_code,
            content=client_error.content,
            headers=client_error.headers,
        )

    usage = extract_usage(response_body)
    # One resolution for the whole request: the quota charge and the log row must
    # be the same number, and two separate reads could disagree if a concurrent
    # lookup landed between them.
    cost = await _orcarouter_request_cost(effective_model, usage)
    await _finalize_or_release_orcarouter_reservation(
        reservation,
        api_key=api_key,
        model=effective_model,
        usage=usage,
        cost=cost,
    )
    await _log_orcarouter_request(
        api_key=api_key,
        model=effective_model,
        started_at=requested_at,
        status="success",
        usage=usage,
        reasoning_effort=sidecar_payload.effective_reasoning_effort,
        requested_reasoning_effort=sidecar_payload.requested_reasoning_effort,
        cost=cost,
    )
    if deepseek_scope is not None:
        deepseek_capture_non_streaming(deepseek_scope, response_body)
    if cursor_compat and is_json_mapping(response_body):
        response_body = apply_cursor_usage_fallback_to_response(
            cast(dict[str, JsonValue], response_body),
            payload,
            source="orcarouter_sidecar_non_stream",
        )
    return JSONResponse(content=response_body, status_code=200, headers=dict(rate_limit_headers))


async def _orcarouter_stream_iterator(
    payload: Mapping[str, JsonValue],
    *,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    model: str,
    started_at: float,
    client: OrcaRouterSidecarClient,
    reasoning_effort: str | None = None,
    requested_reasoning_effort: str | None = None,
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
    except OrcaRouterSidecarUnavailableError:
        await _release_orcarouter_reservation(reservation, api_key=api_key)
        await _log_orcarouter_request(
            api_key=api_key,
            model=model,
            started_at=started_at,
            status="error",
            error_code="orcarouter_sidecar_unavailable",
            error_message="OrcaRouter sidecar unavailable",
            reasoning_effort=reasoning_effort,
            requested_reasoning_effort=requested_reasoning_effort,
        )
        settled = True
        yield _error_sse(
            openai_error(
                "orcarouter_sidecar_unavailable",
                "OrcaRouter sidecar unavailable",
                error_type="upstream_error",
            )
        )
        yield b"data: [DONE]\n\n"
    except OrcaRouterSidecarError as exc:
        await _release_orcarouter_reservation(reservation, api_key=api_key)
        await _log_orcarouter_request(
            api_key=api_key,
            model=model,
            started_at=started_at,
            status="error",
            error_code="orcarouter_sidecar_error",
            error_message=sanitize_orcarouter_message(exc.message, api_key=client.config.api_key),
            reasoning_effort=reasoning_effort,
            requested_reasoning_effort=requested_reasoning_effort,
        )
        settled = True
        client_error = client_facing_sidecar_error(
            status_code=exc.status_code,
            message=sanitize_orcarouter_message(exc.message, api_key=client.config.api_key),
            error_code="orcarouter_sidecar_error",
            body=sanitize_orcarouter_error_body(exc.body, api_key=client.config.api_key),
        )
        yield _error_sse(client_error.content)
        yield b"data: [DONE]\n\n"
    except BaseException as exc:
        await _release_orcarouter_reservation(reservation, api_key=api_key)
        await _log_orcarouter_request(
            api_key=api_key,
            model=model,
            started_at=started_at,
            status="error",
            error_code="orcarouter_sidecar_stream_interrupted",
            error_message=sanitize_orcarouter_message(
                str(exc) or exc.__class__.__name__,
                api_key=client.config.api_key,
            ),
            reasoning_effort=reasoning_effort,
            requested_reasoning_effort=requested_reasoning_effort,
        )
        settled = True
        raise
    finally:
        if not settled:
            usage_to_settle = usage if completed else None
            cost = await _orcarouter_request_cost(model, usage_to_settle)
            await _finalize_or_release_orcarouter_reservation(
                reservation,
                api_key=api_key,
                model=model,
                usage=usage_to_settle,
                cost=cost,
            )
            await _log_orcarouter_request(
                api_key=api_key,
                model=model,
                started_at=started_at,
                status="success" if completed else "error",
                error_code=None if completed else "orcarouter_sidecar_stream_incomplete",
                usage=usage_to_settle,
                reasoning_effort=reasoning_effort,
                requested_reasoning_effort=requested_reasoning_effort,
                cost=cost,
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


def _error_sse(error: OpenAIErrorEnvelope) -> bytes:
    data = json.dumps(error, ensure_ascii=True, separators=(",", ":"))
    return f"data: {data}\n\n".encode("utf-8")


async def _orcarouter_request_cost(model: str, usage: SidecarUsage | None) -> ExternalRequestCost:
    """Resolve this request's cost once, for both the quota charge and the log."""

    return await external_request_cost(
        provider=ORCAROUTER_PRICING_PROVIDER,
        model=model,
        usage=usage_tokens_from_sidecar(usage),
        billed_cost_usd=usage.cost_usd if usage else None,
    )


async def _log_orcarouter_request(
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
    cost: ExternalRequestCost | None = None,
) -> None:
    try:
        # Resolved from persisted state before the write: an already-priced id
        # costs one indexed read and never touches the network here. A caller that
        # also settled a reservation for this request passes the answer it used,
        # so the quota and the log row cannot disagree.
        if cost is None:
            cost = await _orcarouter_request_cost(model, usage)
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
                source=ORCAROUTER_SIDECAR_SOURCE,
                failure_phase="sidecar" if status != "success" else None,
                cost_usd=cost.cost_usd,
                cost_source=cost.cost_source,
                price_status=cost.price_status,
                reference_cost_usd=reference_cost_from_sidecar_usage(
                    model,
                    usage,
                    provider=ORCAROUTER_PRICING_PROVIDER,
                ),
            )
    except Exception:
        logger.warning(
            "failed to write OrcaRouter sidecar request log key_id=%s request_id=%s",
            api_key.id if api_key else None,
            get_request_id(),
            exc_info=True,
        )


async def _finalize_or_release_orcarouter_reservation(
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
                # Stated explicitly so settlement cannot fall through to the
                # substring-glob table this integration no longer prices from.
                cost_microdollars=cost_microdollars(cost),
            )
    except Exception:
        logger.warning(
            "failed to settle OrcaRouter sidecar API key reservation key_id=%s request_id=%s",
            api_key.id if api_key else None,
            get_request_id(),
            exc_info=True,
        )


async def _release_orcarouter_reservation(
    reservation: ApiKeyUsageReservationData | None,
    *,
    api_key: ApiKeyData | None,
) -> None:
    await _finalize_or_release_orcarouter_reservation(
        reservation,
        api_key=api_key,
        model=reservation.model if reservation else "",
        usage=None,
    )
