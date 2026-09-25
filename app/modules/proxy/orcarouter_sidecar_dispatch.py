from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import aclosing
from dataclasses import dataclass
from functools import partial
from typing import cast

from fastapi import Request, Response
from fastapi.responses import JSONResponse

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
from app.core.types import JsonValue
from app.core.usage.logs import CANCELLED_STATUS, CLIENT_DISCONNECT_ERROR_CODE
from app.core.utils.cancellation import complete_despite_cancellation
from app.core.utils.client_disconnect import ClientDisconnected
from app.core.utils.json_guards import is_json_mapping
from app.core.utils.request_id import get_request_id
from app.core.utils.sse import SSE_DONE, SseJsonDataDecoder, inject_sse_keepalives
from app.core.utils.stream_close import ClosingStreamingResponse
from app.db.models import DashboardSettings
from app.db.session import get_background_session
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyData, ApiKeysService, ApiKeyUsageReservationData
from app.modules.proxy.alias_pool_attempts import (
    ChatRequestAttribution,
    PoolTargetFailed,
    PoolTargetUnavailable,
    retryable_failure_from_error,
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
    cost_microdollars,
    external_request_cost,
    external_response_settlement,
    usage_tokens_from_sidecar,
)
from app.modules.proxy.sidecar_model_profiles import read_reasoning_effort, set_reasoning_effort_override
from app.modules.proxy.sidecar_routing import (
    SidecarRoutingEntry,
    parse_sidecar_full_models,
    parse_sidecar_prefixes,
)
from app.modules.proxy.sidecar_upstream_errors import (
    call_with_sidecar_provider_retry,
    client_disconnected_response,
    client_facing_sidecar_error,
    has_usable_sidecar_api_key,
    open_sidecar_stream_for_client,
    relay_sidecar_stream,
    sidecar_not_configured_error,
)
from app.modules.request_logs.repository import RequestLogsRepository

logger = logging.getLogger(__name__)

ORCAROUTER_SIDECAR_SOURCE = "orcarouter_sidecar"

_NOT_CONFIGURED_CODE = "orcarouter_not_configured"
_NOT_CONFIGURED_MESSAGE = "OrcaRouter is enabled but no API key is configured."
#: A refusal sent nothing upstream: no usage, and no price to resolve. Passing
#: this keeps the log write from scheduling a price lookup, which would call
#: the upstream's model listing without a key.
_UNSENT_COST = ExternalRequestCost(cost_usd=None, cost_source=None, price_status=None)


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
    attribution: ChatRequestAttribution | None = None,
    allow_failover: bool = False,
) -> Response:
    """Serve one chat request through OrcaRouter.

    ``effective_model`` is the model being dispatched (the pool target for an
    aliased request); ``attribution`` labels the request-log row with the
    client-facing model and defaults to ``effective_model``. With
    ``allow_failover`` an open-time failure the alias pool loop may retry is
    raised as :class:`PoolTargetFailed` before anything is settled or logged;
    the loop renders it through the carried closure if it turns out to be the
    last attempt.

    Streaming opens the upstream *before* the ``StreamingResponse`` exists, so
    an upstream 4xx/5xx is a JSON error with the upstream status rather than an
    error frame inside a committed ``200 text/event-stream``.

    A provider failure (HTTP 500 or above, transport included) before any
    upstream byte is relayed is sent once more to the same target, so
    OrcaRouter can choose another provider. Inside a pool that retry belongs to
    the target: the loop fails over only after the target's retry failed too.
    """

    attribution = attribution or ChatRequestAttribution.direct(effective_model)
    # Credential gate first, before the payload is built or sent. OrcaRouter
    # authenticates every request, so without a key the upstream can only refuse
    # it - after the caller's prompt has already left the process.
    if not has_usable_sidecar_api_key(client.config.api_key):
        return await _orcarouter_not_configured_response(
            effective_model=effective_model,
            attribution=attribution,
            api_key=api_key,
            reservation=reservation,
            rate_limit_headers=rate_limit_headers,
            allow_failover=allow_failover,
        )
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
        open_stream = partial(client.stream_chat_completion, sidecar_payload.body)
        try:
            opened = await open_sidecar_stream_for_client(
                request.receive, open_stream, provider="OrcaRouter", model=effective_model
            )
        except (ClientDisconnected, asyncio.CancelledError) as exc:
            await complete_despite_cancellation(
                _abandon_orcarouter_request(
                    reservation,
                    api_key=api_key,
                    model=effective_model,
                    attribution=attribution,
                    started_at=requested_at,
                    reasoning_effort=sidecar_payload.effective_reasoning_effort,
                    requested_reasoning_effort=sidecar_payload.requested_reasoning_effort,
                )
            )
            if isinstance(exc, asyncio.CancelledError):
                raise
            return client_disconnected_response()
        except OrcaRouterSidecarError as exc:
            return await _orcarouter_open_error_response(
                exc,
                payload=payload,
                effective_model=effective_model,
                attribution=attribution,
                api_key=api_key,
                reservation=reservation,
                rate_limit_headers=rate_limit_headers,
                client=client,
                cursor_compat=cursor_compat,
                allow_failover=allow_failover,
                sidecar_payload=sidecar_payload,
                started_at=requested_at,
            )
        stream: AsyncIterator[bytes] = _orcarouter_stream_iterator(
            relay_sidecar_stream(opened, open_stream, provider="OrcaRouter", model=effective_model),
            api_key=api_key,
            reservation=reservation,
            model=effective_model,
            attribution=attribution,
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
        return ClosingStreamingResponse(
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
            provider="OrcaRouter",
            model=effective_model,
        )
    except OrcaRouterSidecarError as exc:
        return await _orcarouter_open_error_response(
            exc,
            payload=payload,
            effective_model=effective_model,
            attribution=attribution,
            api_key=api_key,
            reservation=reservation,
            rate_limit_headers=rate_limit_headers,
            client=client,
            cursor_compat=cursor_compat,
            allow_failover=allow_failover,
            sidecar_payload=sidecar_payload,
            started_at=requested_at,
        )

    usage = extract_usage(response_body)
    billed_cost_usd = extract_billed_cost(response_body)
    # One resolution for the whole request: the quota charge and the log row must
    # be the same number, and two separate reads could disagree if a concurrent
    # lookup landed between them.
    cost = await _orcarouter_request_cost(effective_model, usage, billed_cost_usd=billed_cost_usd)
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
        attribution=attribution,
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


async def _orcarouter_not_configured_response(
    *,
    effective_model: str,
    attribution: ChatRequestAttribution,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    rate_limit_headers: Mapping[str, str],
    allow_failover: bool,
) -> Response:
    """Refuse a request OrcaRouter cannot authenticate, sending nothing.

    Inside a pool the target is skipped instead: the loop tries the next one,
    and this attempt leaves no log row and does not touch the reservation.
    """

    if allow_failover:
        raise PoolTargetUnavailable(effective_model, reason="not_configured", provider="orcarouter")
    await _release_orcarouter_reservation(reservation, api_key=api_key)
    await _log_orcarouter_request(
        api_key=api_key,
        model=effective_model,
        attribution=attribution,
        started_at=time.monotonic(),
        status="error",
        error_code=_NOT_CONFIGURED_CODE,
        error_message=_NOT_CONFIGURED_MESSAGE,
        cost=_UNSENT_COST,
    )
    refusal = sidecar_not_configured_error(
        error_code=_NOT_CONFIGURED_CODE,
        message=_NOT_CONFIGURED_MESSAGE,
        extra_headers=rate_limit_headers,
    )
    return JSONResponse(status_code=refusal.status_code, content=refusal.content, headers=refusal.headers)


async def _orcarouter_open_error_response(
    exc: OrcaRouterSidecarError,
    *,
    payload: ChatCompletionsRequest,
    effective_model: str,
    attribution: ChatRequestAttribution,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    rate_limit_headers: Mapping[str, str],
    client: OrcaRouterSidecarClient,
    cursor_compat: bool,
    allow_failover: bool,
    sidecar_payload: OrcaRouterChatPayload,
    started_at: float,
) -> Response:
    """Turn an upstream failure that happened before any client byte into a response.

    Shared by the streaming open and the non-streaming call. When the caller
    allows failover and the failure is retryable, the settle/log/render work
    is deferred into :class:`PoolTargetFailed` so a later target can take the
    request without this attempt leaving a log row or touching the reservation.
    """

    sanitized_message = sanitize_orcarouter_message(exc.message, api_key=client.config.api_key)
    # A cursor-compat context-length response is turned into a synthetic
    # SUCCESS for the client, so it must not fall through to the error
    # settlement below: that would log it as an error and finalize a
    # reservation the client was never charged for. It also must win over
    # failover: another target would hit the same limit. Mirrors the
    # OpenRouter path.
    if (
        cursor_compat
        and not isinstance(exc, OrcaRouterSidecarUnavailableError)
        and is_sidecar_context_length_error(body=exc.body, message=exc.message)
    ):
        await _release_orcarouter_reservation(reservation, api_key=api_key)
        return cursor_context_limit_usage_completion(payload, headers=dict(rate_limit_headers))

    async def render() -> Response:
        if isinstance(exc, OrcaRouterSidecarUnavailableError):
            await _release_orcarouter_reservation(reservation, api_key=api_key)
            await _log_orcarouter_request(
                api_key=api_key,
                model=effective_model,
                attribution=attribution,
                started_at=started_at,
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
        settlement = await external_response_settlement(
            provider=ORCAROUTER_PRICING_PROVIDER,
            model=effective_model,
            usage=extract_usage(exc.body),
            billed_cost_usd=extract_billed_cost(exc.body),
            completed=False,
        )
        await _finalize_or_release_orcarouter_reservation(
            reservation,
            api_key=api_key,
            model=effective_model,
            usage=settlement.usage,
            cost=settlement.cost,
        )
        await _log_orcarouter_request(
            api_key=api_key,
            model=effective_model,
            attribution=attribution,
            started_at=started_at,
            status="error",
            error_code="orcarouter_sidecar_error",
            error_message=sanitized_message,
            usage=settlement.usage,
            reasoning_effort=sidecar_payload.effective_reasoning_effort,
            requested_reasoning_effort=sidecar_payload.requested_reasoning_effort,
            cost=settlement.cost,
        )
        client_error = client_facing_sidecar_error(
            status_code=exc.status_code,
            message=sanitized_message,
            error_code="orcarouter_sidecar_error",
            body=sanitize_orcarouter_error_body(exc.body, api_key=client.config.api_key),
            extra_headers=rate_limit_headers,
        )
        return JSONResponse(
            status_code=client_error.status_code,
            content=client_error.content,
            headers=client_error.headers,
        )

    if allow_failover:
        failure = retryable_failure_from_error(
            status_code=exc.status_code,
            message=sanitized_message,
            headers=exc.rate_limit_headers,
        )
        if failure is not None:
            raise PoolTargetFailed(failure, render=render) from exc
    return await render()


async def _orcarouter_stream_iterator(
    chunks: AsyncGenerator[bytes, None],
    *,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    model: str,
    attribution: ChatRequestAttribution,
    started_at: float,
    client: OrcaRouterSidecarClient,
    reasoning_effort: str | None = None,
    requested_reasoning_effort: str | None = None,
) -> AsyncIterator[bytes]:
    """Relay an already-open upstream stream and settle when it ends.

    ``chunks`` is the ``relay_sidecar_stream`` of an upstream opened before the
    client response was committed; closing it closes the upstream, which
    happens here on completion, on a mid-stream error, and on client
    disconnect. Only mid-stream failures reach the ``except`` branches: the
    open-time ones were handled by the caller as a JSON error, and a failure
    before the first chunk was already retried once by the relay.
    """

    usage: SidecarUsage | None = None
    billed_cost = BilledCostAccumulator()
    completed = False
    error_code = "orcarouter_sidecar_stream_incomplete"
    error_message: str | None = None
    try:
        async with aclosing(chunks):
            decoder = SseJsonDataDecoder()
            async for raw_chunk in chunks:
                for event in decoder.feed(raw_chunk):
                    if event == SSE_DONE:
                        completed = True
                        continue
                    event_usage = extract_usage(event)
                    if event_usage is not None:
                        usage = event_usage
                    billed_cost.observe(extract_billed_cost(event))
                yield raw_chunk
            for event in decoder.flush():
                if event == SSE_DONE:
                    completed = True
                    continue
                event_usage = extract_usage(event)
                if event_usage is not None:
                    usage = event_usage
                billed_cost.observe(extract_billed_cost(event))
    except OrcaRouterSidecarUnavailableError:
        error_code = "orcarouter_sidecar_unavailable"
        error_message = "OrcaRouter sidecar unavailable"
        yield _error_sse(
            openai_error(
                "orcarouter_sidecar_unavailable",
                "OrcaRouter sidecar unavailable",
                error_type="upstream_error",
            )
        )
        yield b"data: [DONE]\n\n"
    except OrcaRouterSidecarError as exc:
        error_code = "orcarouter_sidecar_error"
        error_message = sanitize_orcarouter_message(exc.message, api_key=client.config.api_key)
        billed_cost.observe(extract_billed_cost(exc.body))
        client_error = client_facing_sidecar_error(
            status_code=exc.status_code,
            message=error_message,
            error_code="orcarouter_sidecar_error",
            body=sanitize_orcarouter_error_body(exc.body, api_key=client.config.api_key),
        )
        yield _error_sse(client_error.content)
        yield b"data: [DONE]\n\n"
    except BaseException as exc:
        error_code = "orcarouter_sidecar_stream_interrupted"
        error_message = sanitize_orcarouter_message(
            str(exc) or exc.__class__.__name__,
            api_key=client.config.api_key,
        )
        raise
    finally:
        settlement = await external_response_settlement(
            provider=ORCAROUTER_PRICING_PROVIDER,
            model=model,
            usage=usage,
            billed_cost_usd=billed_cost.value,
            completed=completed,
        )
        await _finalize_or_release_orcarouter_reservation(
            reservation,
            api_key=api_key,
            model=model,
            usage=settlement.usage,
            cost=settlement.cost,
        )
        await _log_orcarouter_request(
            api_key=api_key,
            model=model,
            attribution=attribution,
            started_at=started_at,
            status="success" if completed else "error",
            error_code=None if completed else error_code,
            error_message=None if completed else error_message,
            usage=settlement.usage,
            reasoning_effort=reasoning_effort,
            requested_reasoning_effort=requested_reasoning_effort,
            cost=settlement.cost,
        )


def _error_sse(error: OpenAIErrorEnvelope) -> bytes:
    data = json.dumps(error, ensure_ascii=True, separators=(",", ":"))
    return f"data: {data}\n\n".encode("utf-8")


async def _orcarouter_request_cost(
    model: str,
    usage: SidecarUsage | None,
    *,
    billed_cost_usd: float | None = None,
) -> ExternalRequestCost:
    """Resolve this request's cost once, for both the quota charge and the log."""

    return await external_request_cost(
        provider=ORCAROUTER_PRICING_PROVIDER,
        model=model,
        usage=usage_tokens_from_sidecar(usage),
        billed_cost_usd=billed_cost_usd if billed_cost_usd is not None else usage.cost_usd if usage else None,
    )


async def _log_orcarouter_request(
    *,
    api_key: ApiKeyData | None,
    model: str,
    started_at: float,
    status: str,
    attribution: ChatRequestAttribution | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    usage: SidecarUsage | None = None,
    reasoning_effort: str | None = None,
    requested_reasoning_effort: str | None = None,
    cost: ExternalRequestCost | None = None,
) -> None:
    """Write the request-log row.

    ``model`` is the dispatched model and drives pricing; ``attribution`` is
    what the row is labelled with (the client-facing alias for aliased
    requests) and defaults to ``model``.
    """

    attribution = attribution or ChatRequestAttribution.direct(model)
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
                model=attribution.model,
                upstream_model=attribution.upstream_model,
                pool_attempts=attribution.pool_attempts,
                latency_queue_ms=attribution.queue_ms,
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
                # substring-glob table this integration no longer prices from.
                cost_microdollars=charge_microdollars,
            )
    except Exception:
        logger.warning(
            "failed to settle OrcaRouter sidecar API key reservation key_id=%s request_id=%s",
            api_key.id if api_key else None,
            get_request_id(),
            exc_info=True,
        )


async def _abandon_orcarouter_request(
    reservation: ApiKeyUsageReservationData | None,
    *,
    api_key: ApiKeyData | None,
    model: str,
    attribution: ChatRequestAttribution,
    started_at: float,
    reasoning_effort: str | None,
    requested_reasoning_effort: str | None,
) -> None:
    """Release and log a request whose client left before the upstream answered."""

    await _release_orcarouter_reservation(reservation, api_key=api_key)
    await _log_orcarouter_request(
        api_key=api_key,
        model=model,
        attribution=attribution,
        started_at=started_at,
        status=CANCELLED_STATUS,
        error_code=CLIENT_DISCONNECT_ERROR_CODE,
        error_message="client disconnected before the upstream response started",
        reasoning_effort=reasoning_effort,
        requested_reasoning_effort=requested_reasoning_effort,
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
