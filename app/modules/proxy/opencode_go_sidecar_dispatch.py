"""Dispatch a chat-completions request to OpenCode Go.

Follows the OrcaRouter dispatch shape. The differences that matter:

* The requested model is checked against the reviewed protocol map before any
  upstream call. A model Go serves on ``/messages`` or ``/responses`` is
  rejected with an explanatory 400 rather than silently sent to
  ``/chat/completions``, which the upstream answers with a format error that
  reads to a client like a bad request of its own making.
* Client headers are threaded through so the session resolver can derive the
  outbound ``x-opencode-session``. Nothing else from the inbound request is
  forwarded; the client builds its own header dict from stored configuration.
* ``Retry-After`` from a 429 is relayed verbatim. Only the upstream knows when
  its own window reopens.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import cast

from fastapi import Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.clients.opencode_go_sidecar import (
    OPENCODE_GO_PRICING_PROVIDER,
    OPENCODE_GO_PROVIDER,
    OpenCodeGoSidecarClient,
    OpenCodeGoSidecarConfig,
    OpenCodeGoSidecarError,
    OpenCodeGoSidecarUnavailableError,
    sanitize_opencode_go_error_body,
    sanitize_opencode_go_message,
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
    extract_billed_cost,
    extract_usage,
)
from app.modules.proxy.external_pricing_logging import (
    BilledCostAccumulator,
    ExternalRequestCost,
    cost_microdollars,
    external_request_cost,
    external_response_settlement,
    usage_tokens_from_sidecar,
)
from app.modules.proxy.opencode_go_models import (
    is_opencode_go_model_supported,
    unsupported_model_message,
)
from app.modules.proxy.sidecar_routing import (
    SidecarRoutingEntry,
    parse_sidecar_full_models,
    parse_sidecar_prefixes,
)
from app.modules.proxy.sidecar_upstream_errors import client_facing_sidecar_error
from app.modules.request_logs.repository import RequestLogsRepository

logger = logging.getLogger(__name__)

#: ``RequestLog.source`` for every row this dispatcher writes. Distinct from the
#: pricing provider key on purpose: the log records the serving integration.
OPENCODE_GO_SIDECAR_SOURCE = "opencode_go_sidecar"

_UNSUPPORTED_MODEL_CODE = "opencode_go_model_unsupported"


@dataclass(frozen=True, slots=True)
class OpenCodeGoChatPayload:
    body: dict[str, JsonValue]


def opencode_go_routing_entry(config: OpenCodeGoSidecarConfig) -> SidecarRoutingEntry:
    return SidecarRoutingEntry(
        provider=OPENCODE_GO_PROVIDER,
        prefixes=config.prefixes,
        full_models=config.full_models,
    )


async def load_opencode_go_sidecar_config() -> OpenCodeGoSidecarConfig | None:
    try:
        dashboard_settings = await get_settings_cache().get()
    except Exception:
        logger.warning("failed to load dashboard settings for OpenCode Go", exc_info=True)
        return None
    return opencode_go_sidecar_config_from_settings(dashboard_settings)


def opencode_go_sidecar_config_from_settings(settings: DashboardSettings) -> OpenCodeGoSidecarConfig:
    """The one place the OpenCode Go credential is decrypted.

    Other lanes (the ``/usage`` quota poller) read the key through this function
    rather than reaching into the column, so there is a single audited point of
    access and a single place a decryption failure is handled.
    """

    return OpenCodeGoSidecarConfig(
        enabled=bool(settings.opencode_go_sidecar_enabled),
        base_url=settings.opencode_go_sidecar_base_url.rstrip("/"),
        api_key=_decrypt_opencode_go_secret(settings.opencode_go_sidecar_api_key_encrypted),
        prefixes=parse_sidecar_prefixes(settings.opencode_go_sidecar_model_prefixes_json),
        connect_timeout_seconds=settings.opencode_go_sidecar_connect_timeout_seconds,
        request_timeout_seconds=settings.opencode_go_sidecar_request_timeout_seconds,
        models_cache_ttl_seconds=settings.opencode_go_sidecar_models_cache_ttl_seconds,
        full_models=parse_sidecar_full_models(settings.opencode_go_sidecar_full_models_json),
    )


def _decrypt_opencode_go_secret(encrypted: bytes | None) -> str | None:
    if not encrypted:
        return None
    try:
        return TokenEncryptor().decrypt(encrypted)
    except Exception:
        logger.warning("failed to decrypt OpenCode Go API key", exc_info=True)
        return None


def build_opencode_go_chat_payload(
    payload: ChatCompletionsRequest,
    effective_model: str,
) -> OpenCodeGoChatPayload:
    body = cast(dict[str, JsonValue], payload.model_dump(mode="json", exclude_none=True))
    # ``effective_model`` is the wire model already resolved (and stripped per
    # the matched prefix's flag) by the unified resolver.
    body["model"] = effective_model.strip()
    return OpenCodeGoChatPayload(body=body)


async def proxy_chat_to_opencode_go(
    request: Request,
    payload: ChatCompletionsRequest,
    *,
    effective_model: str,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    rate_limit_headers: Mapping[str, str],
    sse_keepalive_interval_seconds: float,
    client: OpenCodeGoSidecarClient,
    wire_model: str | None = None,
) -> Response:
    forward_model = wire_model or effective_model
    requested_at = time.monotonic()

    # Protocol gate before any upstream call. Go serves this catalogue across
    # three differently-shaped endpoints, and which model lives where is per
    # model. Sending a ``/messages`` model to ``/chat/completions`` returns a
    # 200-shaped format error or an opaque 400, so refusing here is both
    # cheaper and far more legible than relaying the upstream's complaint.
    if not is_opencode_go_model_supported(forward_model):
        message = unsupported_model_message(forward_model)
        await _release_opencode_go_reservation(reservation, api_key=api_key)
        await _log_opencode_go_request(
            api_key=api_key,
            model=effective_model,
            started_at=requested_at,
            status="error",
            error_code=_UNSUPPORTED_MODEL_CODE,
            error_message=message,
        )
        return JSONResponse(
            status_code=400,
            content=openai_error(_UNSUPPORTED_MODEL_CODE, message, error_type="invalid_request_error"),
            headers=dict(rate_limit_headers),
        )

    sidecar_payload = build_opencode_go_chat_payload(payload, forward_model)
    # Captured once, here: the inbound headers are read only to resolve the
    # conversation identity, never merged into the outbound header set.
    client_headers = dict(request.headers)

    if payload.stream:
        ensure_stream_usage_requested(sidecar_payload.body)
        stream: AsyncIterator[bytes] = _opencode_go_stream_iterator(
            sidecar_payload.body,
            api_key=api_key,
            reservation=reservation,
            model=effective_model,
            started_at=requested_at,
            client=client,
            client_headers=client_headers,
        )
        return StreamingResponse(
            inject_sse_keepalives(stream, sse_keepalive_interval_seconds),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", **dict(rate_limit_headers)},
        )

    try:
        response_body = await client.chat_completion(sidecar_payload.body, client_headers=client_headers)
    except OpenCodeGoSidecarUnavailableError:
        await _release_opencode_go_reservation(reservation, api_key=api_key)
        await _log_opencode_go_request(
            api_key=api_key,
            model=effective_model,
            started_at=requested_at,
            status="error",
            error_code="opencode_go_sidecar_unavailable",
            error_message="OpenCode Go unavailable",
        )
        return JSONResponse(
            status_code=503,
            content=openai_error(
                "opencode_go_sidecar_unavailable",
                "OpenCode Go unavailable",
                error_type="upstream_error",
            ),
            headers=dict(rate_limit_headers),
        )
    except OpenCodeGoSidecarError as exc:
        sanitized_message = sanitize_opencode_go_message(exc.message, api_key=client.config.api_key)
        settlement = await external_response_settlement(
            provider=OPENCODE_GO_PRICING_PROVIDER,
            model=effective_model,
            usage=extract_usage(exc.body),
            billed_cost_usd=extract_billed_cost(exc.body),
            completed=False,
        )
        await _finalize_or_release_opencode_go_reservation(
            reservation,
            api_key=api_key,
            model=effective_model,
            usage=settlement.usage,
            cost=settlement.cost,
        )
        await _log_opencode_go_request(
            api_key=api_key,
            model=effective_model,
            started_at=requested_at,
            status="error",
            error_code="opencode_go_sidecar_error",
            error_message=sanitized_message,
            usage=settlement.usage,
            cost=settlement.cost,
        )
        client_error = client_facing_sidecar_error(
            status_code=exc.status_code,
            message=sanitized_message,
            error_code="opencode_go_sidecar_error",
            body=sanitize_opencode_go_error_body(exc.body, api_key=client.config.api_key),
            extra_headers=_headers_with_retry_after(rate_limit_headers, exc),
        )
        return JSONResponse(
            status_code=client_error.status_code,
            content=client_error.content,
            headers=client_error.headers,
        )

    usage = extract_usage(response_body)
    # One resolution for the whole request: the quota charge and the log row
    # must be the same number, and two separate reads could disagree if a
    # concurrent lookup landed between them.
    cost = await _opencode_go_request_cost(effective_model, usage, billed_cost_usd=extract_billed_cost(response_body))
    await _finalize_or_release_opencode_go_reservation(
        reservation,
        api_key=api_key,
        model=effective_model,
        usage=usage,
        cost=cost,
    )
    await _log_opencode_go_request(
        api_key=api_key,
        model=effective_model,
        started_at=requested_at,
        status="success",
        usage=usage,
        cost=cost,
    )
    return JSONResponse(content=response_body, status_code=200, headers=dict(rate_limit_headers))


def _headers_with_retry_after(
    rate_limit_headers: Mapping[str, str],
    exc: OpenCodeGoSidecarError,
) -> dict[str, str]:
    """Relay the upstream ``Retry-After`` verbatim when it sent one.

    Not recomputed: only the upstream knows when its own rate-limit window
    reopens, and a locally invented value that is too short turns one 429 into
    a retry storm against a subscription with hard dollar caps.
    ``client_facing_sidecar_error`` sets its own Retry-After for the 401/403
    remap; this only supplies one the upstream actually published.
    """

    headers = dict(rate_limit_headers)
    if exc.retry_after:
        headers["Retry-After"] = exc.retry_after
    return headers


async def _opencode_go_stream_iterator(
    payload: Mapping[str, JsonValue],
    *,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    model: str,
    started_at: float,
    client: OpenCodeGoSidecarClient,
    client_headers: Mapping[str, str] | None = None,
) -> AsyncIterator[bytes]:
    usage: SidecarUsage | None = None
    billed_cost = BilledCostAccumulator()
    completed = False
    error_code = "opencode_go_sidecar_stream_incomplete"
    error_message: str | None = None
    try:
        async with client.stream_chat_completion(payload, client_headers=client_headers) as chunks:
            decoder = _SseUsageDecoder()
            async for raw_chunk in chunks:
                for event in decoder.feed(raw_chunk.decode("utf-8", errors="ignore")):
                    if event == "[DONE]":
                        completed = True
                        continue
                    event_usage = extract_usage(event)
                    if event_usage is not None:
                        usage = event_usage
                    billed_cost.observe(extract_billed_cost(event))
                yield raw_chunk
            for event in decoder.flush():
                if event == "[DONE]":
                    completed = True
                    continue
                event_usage = extract_usage(event)
                if event_usage is not None:
                    usage = event_usage
                billed_cost.observe(extract_billed_cost(event))
    except OpenCodeGoSidecarUnavailableError:
        error_code = "opencode_go_sidecar_unavailable"
        error_message = "OpenCode Go unavailable"
        yield _error_sse(
            openai_error(
                "opencode_go_sidecar_unavailable",
                "OpenCode Go unavailable",
                error_type="upstream_error",
            )
        )
        yield b"data: [DONE]\n\n"
    except OpenCodeGoSidecarError as exc:
        error_code = "opencode_go_sidecar_error"
        error_message = sanitize_opencode_go_message(exc.message, api_key=client.config.api_key)
        billed_cost.observe(extract_billed_cost(exc.body))
        client_error = client_facing_sidecar_error(
            status_code=exc.status_code,
            message=error_message,
            error_code="opencode_go_sidecar_error",
            body=sanitize_opencode_go_error_body(exc.body, api_key=client.config.api_key),
        )
        yield _error_sse(client_error.content)
        yield b"data: [DONE]\n\n"
    except BaseException as exc:
        # Covers client disconnect and task cancellation. The ``finally`` block
        # below still settles the reservation and writes the log row, so a
        # cancelled stream can neither leak a reservation nor lose the usage the
        # upstream already reported.
        error_code = "opencode_go_sidecar_stream_interrupted"
        error_message = sanitize_opencode_go_message(
            str(exc) or exc.__class__.__name__,
            api_key=client.config.api_key,
        )
        raise
    finally:
        settlement = await external_response_settlement(
            provider=OPENCODE_GO_PRICING_PROVIDER,
            model=model,
            usage=usage,
            billed_cost_usd=billed_cost.value,
            completed=completed,
        )
        await _finalize_or_release_opencode_go_reservation(
            reservation,
            api_key=api_key,
            model=model,
            usage=settlement.usage,
            cost=settlement.cost,
        )
        await _log_opencode_go_request(
            api_key=api_key,
            model=model,
            started_at=started_at,
            status="success" if completed else "error",
            error_code=None if completed else error_code,
            error_message=None if completed else error_message,
            usage=settlement.usage,
            cost=settlement.cost,
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


async def _opencode_go_request_cost(
    model: str,
    usage: SidecarUsage | None,
    *,
    billed_cost_usd: float | None = None,
) -> ExternalRequestCost:
    """Resolve this request's cost once, for both the quota charge and the log.

    OpenCode Go is a flat $10/month subscription and reports no billed amount,
    so in practice this resolves to a ``catalog_calculated`` figure - a
    **list-price usage estimate, never spend**. The ``billed_cost_usd`` argument
    is still honoured rather than dropped, so that if Go ever does publish a
    per-request amount it is recorded as authoritative instead of being
    shadowed by a computed one.
    """

    return await external_request_cost(
        provider=OPENCODE_GO_PRICING_PROVIDER,
        model=model,
        usage=usage_tokens_from_sidecar(usage),
        billed_cost_usd=billed_cost_usd if billed_cost_usd is not None else usage.cost_usd if usage else None,
    )


async def _log_opencode_go_request(
    *,
    api_key: ApiKeyData | None,
    model: str,
    started_at: float,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
    usage: SidecarUsage | None = None,
    cost: ExternalRequestCost | None = None,
) -> None:
    try:
        # Resolved from persisted state before the write: an already-priced id
        # costs one indexed read and never touches the network here. A caller
        # that also settled a reservation for this request passes the answer it
        # used, so the quota and the log row cannot disagree.
        if cost is None:
            cost = await _opencode_go_request_cost(model, usage)
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
                source=OPENCODE_GO_SIDECAR_SOURCE,
                failure_phase="sidecar" if status != "success" else None,
                cost_usd=cost.cost_usd,
                cost_source=cost.cost_source,
                price_status=cost.price_status,
                # No reference cost: "savings" compares a served request against
                # its paid-equivalent list price, and a flat subscription has no
                # meaningful paid equivalent per request. Reporting one would
                # invent a saving figure out of the same list price already
                # recorded as the cost.
                reference_cost_usd=None,
            )
    except Exception:
        logger.warning(
            "failed to write OpenCode Go request log key_id=%s request_id=%s",
            api_key.id if api_key else None,
            get_request_id(),
            exc_info=True,
        )


async def _finalize_or_release_opencode_go_reservation(
    reservation: ApiKeyUsageReservationData | None,
    *,
    api_key: ApiKeyData | None,
    model: str,
    usage: SidecarUsage | None,
    cost: ExternalRequestCost | None = None,
) -> None:
    """Settle or release one reservation using the caller's resolved cost.

    Settlement resolves nothing itself: doing so would read the store a second
    time inside an open background session, and a concurrent lookup landing
    between the two reads would make the two disagree. No cost means nothing is
    charged.
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
                # Stated explicitly so settlement cannot fall through to the
                # substring-glob table this integration never prices from.
                cost_microdollars=charge_microdollars,
            )
    except Exception:
        logger.warning(
            "failed to settle OpenCode Go API key reservation key_id=%s request_id=%s",
            api_key.id if api_key else None,
            get_request_id(),
            exc_info=True,
        )


async def _release_opencode_go_reservation(
    reservation: ApiKeyUsageReservationData | None,
    *,
    api_key: ApiKeyData | None,
) -> None:
    await _finalize_or_release_opencode_go_reservation(
        reservation,
        api_key=api_key,
        model=reservation.model if reservation else "",
        usage=None,
    )
