"""Send xAI Responses traffic to CLIProxyAPI's native ``/v1/responses``.

Every other CLIProxyAPI model reaches it through the Responses -> chat bridge.
For xAI that bridge is lossy where it matters most: chat has no field for
``reasoning.encrypted_content``, so each earlier reasoning item is dropped and
the prompt xAI sees after a reasoning turn no longer starts with the prefix it
cached. Every later turn is then billed in full. The bridge also drops
Responses-only fields and xAI's exact cost.

CLIProxyAPI's ``/v1/responses`` hands an xAI model's body to its xAI executor,
which posts it to xAI ``/v1/responses`` with only a few edits, so the request
stays whole. This module forwards the client's Responses body there and relays
the Responses answer back unchanged. Account routing, sticky pins, the
cooldown wait, the API-key reservation and request logging are the chat
route's, so the two routes cannot drift apart on those.

The route is behind ``cliproxy_xai_native_responses_enabled``; switching it
off sends xAI back through the bridge. Compaction stays on its own path.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from functools import partial
from typing import cast

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app.core.clients.claude_sidecar import (
    ClaudeSidecarClient,
    ClaudeSidecarError,
    ClaudeSidecarUnavailableError,
)
from app.core.config.settings import get_settings
from app.core.errors import OpenAIErrorEnvelope, openai_error, response_failed_event
from app.core.metrics.prometheus import cliproxy_xai_responses_route_total
from app.core.openai.requests import ResponsesRequest
from app.core.types import JsonValue
from app.core.utils.cancellation import await_deferring_cancellation, complete_despite_cancellation
from app.core.utils.json_guards import is_json_mapping
from app.core.utils.sse import SseJsonDataDecoder, format_sse_event, inject_sse_keepalives
from app.core.utils.stream_close import ClosingStreamingResponse, SettlingStream
from app.modules.api_keys.service import ApiKeyData, ApiKeyUsageReservationData
from app.modules.proxy import claude_sidecar_dispatch
from app.modules.proxy.claude_sidecar_dispatch import (
    _ACCOUNT_REBIND_STATUSES,
    _CLAUDE_SIDECAR_COOLDOWN_GATE,
    SidecarUsage,
    _abandon_unstarted_sidecar_stream,
    _finalize_or_release_sidecar_reservation,
    _finish_claude_sidecar_cooldown_attempt,
    _log_sidecar_request,
    _prepare_claude_sidecar_cooldown_attempt,
    _release_and_log_sidecar_request,
    _release_sidecar_reservation,
    _sidecar_request_cost,
    claude_sidecar_request_log_error,
    extract_usage,
    extract_xai_billed_cost,
    retry_claude_sidecar_cooldown,
)
from app.modules.proxy.cliproxy_account_routing import (
    CliproxyStickyHints,
    apply_cliproxy_account_route,
    cliproxy_conversation_id,
    rebind_cliproxy_account_route,
)
from app.modules.proxy.sidecar_model_profiles import read_reasoning_effort
from app.modules.proxy.sidecar_upstream_errors import client_facing_sidecar_error

logger = logging.getLogger(__name__)

# The sidecar provider id CLIProxyAPI is configured under.
CLIPROXY_PROVIDER = "claude"
NATIVE_ROUTE = "native"
BRIDGE_ROUTE = "bridge"
# Served through, in the 400 that refuses a stateful field on this route.
NATIVE_ROUTE_DESCRIPTION = "CLIProxyAPI's native Responses route, which keeps no stored responses"

_TERMINAL_SUCCESS_EVENTS = frozenset({"response.completed", "response.incomplete"})
_TERMINAL_FAILURE_EVENTS = frozenset({"response.failed", "error"})
_STREAM_INCOMPLETE_ERROR_CODE = "claude_sidecar_stream_incomplete"
_UNAVAILABLE_ERROR_CODE = "claude_sidecar_unavailable"
_UNAVAILABLE_MESSAGE = "Claude sidecar unavailable"
_UPSTREAM_FAILED_ERROR_CODE = "cliproxy_xai_response_failed"
# Responses-shaped twin of the chat route's shutdown frame: a Responses
# client stops at ``response.failed`` and can retry the turn.
_SHUTDOWN_RESPONSE_FAILED_FRAME = format_sse_event(
    cast(
        Mapping[str, JsonValue],
        response_failed_event("service_unavailable", "503 service unavailable"),
    )
)


def is_cliproxy_xai_model(wire_model: str) -> bool:
    """Whether CLIProxyAPI serves ``wire_model`` with its xAI executor.

    Only a plain ``grok`` id qualifies. A prefixed id such as ``devin/grok-4-6``
    names another executor that also lists grok models, and CLIProxyAPI's
    ``/v1/responses`` would hand that executor a body it does not expect, so
    every prefixed id stays on the chat bridge.
    """

    model = wire_model.strip().casefold()
    return bool(model) and "/" not in model and model.startswith("grok")


def use_cliproxy_xai_native_responses(provider: str, wire_model: str) -> bool:
    return (
        provider == CLIPROXY_PROVIDER
        and is_cliproxy_xai_model(wire_model)
        and get_settings().cliproxy_xai_native_responses_enabled
    )


def record_cliproxy_xai_responses_route(provider: str, wire_model: str, route: str) -> None:
    """Count one xAI Responses request by route; other models are not counted."""

    if provider != CLIPROXY_PROVIDER or not is_cliproxy_xai_model(wire_model):
        return
    if cliproxy_xai_responses_route_total is not None:
        cliproxy_xai_responses_route_total.labels(route=route).inc()


@dataclass(frozen=True, slots=True)
class CliproxyResponsesBody:
    body: dict[str, JsonValue]
    requested_reasoning_effort: str | None
    effective_reasoning_effort: str | None


def build_cliproxy_xai_responses_body(
    payload: ResponsesRequest,
    *,
    wire_model: str,
    conversation_id: str,
    default_reasoning_effort: str | None,
) -> CliproxyResponsesBody:
    """The body sent to CLIProxyAPI: the client's request with three edits.

    ``model`` becomes the routed wire id and ``prompt_cache_key`` the
    conversation id codex-lb pins on, so xAI's cache and the pin agree. An
    operator default effort fills ``reasoning.effort`` only when the client
    sent none: unlike the chat route's override, a client effort is the
    client's to choose here. Everything else, including reasoning items with
    their ``encrypted_content``, is forwarded as sent.
    """

    body = payload.model_dump_for_forwarding()
    body["model"] = wire_model
    body["prompt_cache_key"] = conversation_id
    requested_reasoning_effort = read_reasoning_effort(body)
    default_effort = default_reasoning_effort.strip() if default_reasoning_effort else ""
    if requested_reasoning_effort is None and default_effort:
        reasoning = body.get("reasoning")
        merged: dict[str, JsonValue] = dict(reasoning) if is_json_mapping(reasoning) else {}
        merged["effort"] = default_effort
        body["reasoning"] = merged
    return CliproxyResponsesBody(
        body=body,
        requested_reasoning_effort=requested_reasoning_effort,
        effective_reasoning_effort=read_reasoning_effort(body),
    )


def native_conversation_id(hints: CliproxyStickyHints, headers: Mapping[str, str]) -> str:
    """The ``prompt_cache_key`` sent to CLIProxyAPI, never empty.

    It is the id the sticky pin is keyed on. CLIProxyAPI falls back to an id it
    derives from the opening messages, which collides across conversations that
    open the same way, so a request with no id of its own gets a fresh random
    one. It is not pinned, as codex-lb never pins on a key that cannot recur.
    """

    return cliproxy_conversation_id(hints, headers) or f"codex-lb-{uuid.uuid4().hex}"


async def proxy_responses_to_cliproxy_native(
    request: Request,
    payload: ResponsesRequest,
    *,
    effective_model: str,
    wire_model: str,
    api_key: ApiKeyData | None,
    reservation: ApiKeyUsageReservationData | None,
    rate_limit_headers: Mapping[str, str],
    sse_keepalive_interval_seconds: float,
    client: ClaudeSidecarClient,
    sticky_hints: CliproxyStickyHints,
) -> Response:
    record_cliproxy_xai_responses_route(CLIPROXY_PROVIDER, wire_model, NATIVE_ROUTE)
    built = build_cliproxy_xai_responses_body(
        payload,
        wire_model=wire_model,
        conversation_id=native_conversation_id(sticky_hints, request.headers),
        default_reasoning_effort=client.config.default_reasoning_effort,
    )
    body = built.body
    await apply_cliproxy_account_route(body, headers=request.headers, client=client, hints=sticky_hints)
    requested_at = time.monotonic()
    log_fields = _LogFields(
        api_key=api_key,
        model=effective_model,
        started_at=requested_at,
        reasoning_effort=built.effective_reasoning_effort,
        requested_reasoning_effort=built.requested_reasoning_effort,
    )
    if payload.stream:
        settling = SettlingStream(
            _native_stream(body, client=client, reservation=reservation, log=log_fields),
            abandon=partial(
                _abandon_unstarted_sidecar_stream,
                reservation,
                api_key=api_key,
                model=effective_model,
                started_at=requested_at,
                reasoning_effort=log_fields.reasoning_effort,
                requested_reasoning_effort=log_fields.requested_reasoning_effort,
            ),
        )
        return ClosingStreamingResponse(
            inject_sse_keepalives(
                settling,
                sse_keepalive_interval_seconds,
                shutdown_handoff_frame=_SHUTDOWN_RESPONSE_FAILED_FRAME,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", **dict(rate_limit_headers)},
            settling=settling,
        )

    try:
        response_body = await _responses_with_rebind(client, body)
    except ClaudeSidecarUnavailableError:
        await _release_sidecar_reservation(reservation, api_key=api_key)
        await _log_error(log_fields, error_code=_UNAVAILABLE_ERROR_CODE, error_message=_UNAVAILABLE_MESSAGE)
        return JSONResponse(
            status_code=503,
            content=openai_error(_UNAVAILABLE_ERROR_CODE, _UNAVAILABLE_MESSAGE, error_type="upstream_error"),
            headers=dict(rate_limit_headers),
        )
    except ClaudeSidecarError as exc:
        await _release_sidecar_reservation(reservation, api_key=api_key)
        await _log_upstream_error(log_fields, exc)
        client_error = client_facing_sidecar_error(
            status_code=exc.status_code,
            message=exc.message,
            error_code="claude_sidecar_error",
            body=exc.body,
            extra_headers=rate_limit_headers,
        )
        return JSONResponse(
            status_code=client_error.status_code,
            content=client_error.content,
            headers=client_error.headers,
        )

    await _settle_and_log(
        reservation,
        log=log_fields,
        response=response_body,
        failure=_failure_of_response(response_body),
    )
    return JSONResponse(content=response_body, status_code=200, headers=dict(rate_limit_headers))


@dataclass(frozen=True, slots=True)
class _LogFields:
    api_key: ApiKeyData | None
    model: str
    started_at: float
    reasoning_effort: str | None
    requested_reasoning_effort: str | None


@dataclass(frozen=True, slots=True)
class _UpstreamFailure:
    code: str
    message: str


async def _responses_with_rebind(client: ClaudeSidecarClient, body: dict[str, JsonValue]) -> JsonValue:
    """Send one Responses request, moving the pin once if that credential fails."""

    try:
        return await retry_claude_sidecar_cooldown(lambda: client.responses(body))
    except ClaudeSidecarError as exc:
        if exc.status_code not in _ACCOUNT_REBIND_STATUSES:
            raise
        if await rebind_cliproxy_account_route(body, client=client) is None:
            raise
        return await retry_claude_sidecar_cooldown(lambda: client.responses(body))


class _SseEventFramer:
    """Re-cut a byte stream on SSE event boundaries without changing a byte.

    Upstream chunks split events anywhere. Keepalive comments are injected
    between the chunks this yields, so each one must end on a blank line, or a
    comment would land inside an event and cut it in two.
    """

    def __init__(self) -> None:
        self._pending = bytearray()

    def feed(self, chunk: bytes) -> str:
        self._pending.extend(chunk)
        end = 0
        for separator in (b"\n\n", b"\r\n\r\n"):
            found = self._pending.rfind(separator)
            if found >= 0:
                end = max(end, found + len(separator))
        if end == 0:
            return ""
        complete = _decode_frame(bytes(self._pending[:end]))
        del self._pending[:end]
        return complete

    def flush(self) -> str:
        """Return what is left, closed as an event if the upstream left it open.

        A stream cut mid-event leaves a tail with no blank line. Sent as is,
        whatever follows (a keepalive, or the ``response.failed`` this route
        adds) would join that event and never parse as its own. The decoder
        already reads the tail as an event, so the client sees what codex-lb
        saw.
        """

        rest = bytes(self._pending)
        self._pending.clear()
        if not rest or rest.endswith((b"\n\n", b"\r\n\r\n")):
            return _decode_frame(rest)
        if rest.endswith(b"\r\n"):
            return _decode_frame(rest + b"\r\n")
        if rest.endswith(b"\n"):
            return _decode_frame(rest + b"\n")
        return _decode_frame(rest + b"\n\n")


def _decode_frame(frame: bytes) -> str:
    # Whole events are whole UTF-8 text, so this round-trips byte for byte; a
    # broken upstream byte becomes U+FFFD instead of ending the response.
    return frame.decode("utf-8", errors="replace")


class _StreamObserver:
    """What the relayed events say about the turn: terminal event, usage, cost."""

    def __init__(self) -> None:
        self.terminal: str | None = None
        self.response: JsonValue = None
        self.failure: _UpstreamFailure | None = None

    def observe(self, event: object) -> None:
        if not is_json_mapping(event):
            return
        event_type = event.get("type")
        if not isinstance(event_type, str):
            return
        if event_type in _TERMINAL_SUCCESS_EVENTS or event_type in _TERMINAL_FAILURE_EVENTS:
            self.terminal = event_type
            response = event.get("response")
            self.response = response if is_json_mapping(response) else None
            self.failure = _failure_of_event(event) if event_type in _TERMINAL_FAILURE_EVENTS else None


async def _native_stream(
    body: dict[str, JsonValue],
    *,
    client: ClaudeSidecarClient,
    reservation: ApiKeyUsageReservationData | None,
    log: _LogFields,
) -> AsyncIterator[str]:
    observer = _StreamObserver()
    settled = False
    yielded = False
    account_rebound = False
    # Read at call time, as the chat route does, so a patched or tuned wait
    # applies to both routes alike.
    wait_seconds = claude_sidecar_dispatch.CLAUDE_SIDECAR_COOLDOWN_WAIT_SECONDS
    cooldown_deadline = time.monotonic() + wait_seconds
    last_cooldown_exc: ClaudeSidecarError | None = None
    try:
        while True:
            if last_cooldown_exc is not None and time.monotonic() >= cooldown_deadline:
                raise last_cooldown_exc
            held = False
            if wait_seconds > 0.0:
                held = await _prepare_claude_sidecar_cooldown_attempt(deadline=cooldown_deadline)
                if last_cooldown_exc is not None and time.monotonic() >= cooldown_deadline:
                    if held:
                        await _CLAUDE_SIDECAR_COOLDOWN_GATE.end_poll(held=True)
                    raise last_cooldown_exc
            try:
                observer = _StreamObserver()
                async with client.stream_responses(body) as chunks:
                    decoder = SseJsonDataDecoder()
                    framer = _SseEventFramer()
                    async for raw_chunk in chunks:
                        for event in decoder.feed(raw_chunk):
                            observer.observe(event)
                        frame = framer.feed(raw_chunk)
                        if frame:
                            yielded = True
                            yield frame
                    # Observe the tail before handing it on, as every other
                    # frame is: a client that leaves right after a terminal
                    # tail must still find the turn observed and charged.
                    for event in decoder.flush():
                        observer.observe(event)
                    tail = framer.flush()
                    if tail:
                        yielded = True
                        yield tail
                if wait_seconds > 0.0:
                    await _finish_claude_sidecar_cooldown_attempt(None, deadline=cooldown_deadline, held=held)
                break
            except ClaudeSidecarError as exc:
                if not yielded and not account_rebound and exc.status_code in _ACCOUNT_REBIND_STATUSES:
                    if await rebind_cliproxy_account_route(body, client=client) is not None:
                        account_rebound = True
                        if wait_seconds > 0.0:
                            await _CLAUDE_SIDECAR_COOLDOWN_GATE.end_poll(held=held)
                        continue
                if wait_seconds <= 0.0:
                    raise
                if yielded:
                    await _CLAUDE_SIDECAR_COOLDOWN_GATE.end_poll(held=held)
                    raise
                last_cooldown_exc = exc
                if await _finish_claude_sidecar_cooldown_attempt(exc, deadline=cooldown_deadline, held=held) is None:
                    raise
            except BaseException:
                if wait_seconds > 0.0:
                    # A cancelled request must still hand back the poll slot, or
                    # every later request waits behind a poller that is gone.
                    await await_deferring_cancellation(_CLAUDE_SIDECAR_COOLDOWN_GATE.end_poll(held=held))
                raise
    except ClaudeSidecarError as exc:
        if observer.terminal is not None:
            # The transport failed after the terminal event was read and
            # relayed: xAI finished and billed the turn and the client has its
            # terminal frame. ``finally`` charges it, shielded, from what was
            # observed; nothing is added after the terminal frame.
            return
        await _release_sidecar_reservation(reservation, api_key=log.api_key)
        if isinstance(exc, ClaudeSidecarUnavailableError):
            await _log_error(log, error_code=_UNAVAILABLE_ERROR_CODE, error_message=_UNAVAILABLE_MESSAGE)
            settled = True
            yield _response_failed_frame(
                openai_error(_UNAVAILABLE_ERROR_CODE, _UNAVAILABLE_MESSAGE, error_type="upstream_error")
            )
            return
        await _log_upstream_error(log, exc)
        settled = True
        client_error = client_facing_sidecar_error(
            status_code=exc.status_code,
            message=exc.message,
            error_code="claude_sidecar_error",
            body=exc.body,
        )
        yield _response_failed_frame(client_error.content)
        return
    except BaseException as exc:
        # A client disconnect lands here as a cancellation, inside a cancel scope
        # that re-cancels every plain await - so the settlement and the log must
        # finish shielded, or the reservation stays held with no log row.
        settled = True
        if observer.terminal is not None:
            # The upstream finished the turn before the client left: the
            # terminal event (and its usage) was read before the frame was
            # handed on, so xAI billed it and the key is charged for it.
            await await_deferring_cancellation(
                _settle_and_log(
                    reservation,
                    log=log,
                    response=observer.response,
                    failure=_stream_failure(observer),
                )
            )
            raise
        await await_deferring_cancellation(
            _release_and_log_sidecar_request(
                reservation,
                api_key=log.api_key,
                model=log.model,
                started_at=log.started_at,
                error_code="claude_sidecar_stream_interrupted",
                error_message=str(exc) or exc.__class__.__name__,
                reasoning_effort=log.reasoning_effort,
                requested_reasoning_effort=log.requested_reasoning_effort,
            )
        )
        raise
    finally:
        if not settled:
            await complete_despite_cancellation(
                _settle_and_log(
                    reservation,
                    log=log,
                    response=observer.response,
                    failure=_stream_failure(observer),
                )
            )

    if observer.terminal is None:
        # The upstream closed without a terminal event. A Responses client
        # waits for one, so end the turn as failed instead of leaving it open.
        yield _response_failed_frame(
            openai_error(
                _STREAM_INCOMPLETE_ERROR_CODE,
                "CLIProxyAPI closed the stream before the response finished",
                error_type="upstream_error",
            )
        )


def _stream_failure(observer: _StreamObserver) -> _UpstreamFailure | None:
    if observer.terminal is None:
        return _UpstreamFailure(_STREAM_INCOMPLETE_ERROR_CODE, "stream ended without a terminal event")
    return observer.failure


async def _settle_and_log(
    reservation: ApiKeyUsageReservationData | None,
    *,
    log: _LogFields,
    response: JsonValue,
    failure: _UpstreamFailure | None,
) -> None:
    """Charge and log a turn that reached the upstream.

    A turn that reports usage is charged for it even when it failed, since the
    upstream billed those tokens. One with no usage is released.
    """

    usage: SidecarUsage | None = extract_usage(response)
    xai_cost = extract_xai_billed_cost(response) if usage is not None else None
    cost = await _sidecar_request_cost(log.model, usage, xai_billed_cost_usd=xai_cost)
    await _finalize_or_release_sidecar_reservation(
        reservation,
        api_key=log.api_key,
        model=log.model,
        usage=usage,
        cost=cost,
    )
    await _log_sidecar_request(
        api_key=log.api_key,
        model=log.model,
        started_at=log.started_at,
        status="success" if failure is None else "error",
        error_code=None if failure is None else failure.code,
        error_message=None if failure is None else failure.message,
        usage=usage,
        reasoning_effort=log.reasoning_effort,
        requested_reasoning_effort=log.requested_reasoning_effort,
        cost=cost,
    )


async def _log_error(log: _LogFields, *, error_code: str, error_message: str) -> None:
    await _log_sidecar_request(
        api_key=log.api_key,
        model=log.model,
        started_at=log.started_at,
        status="error",
        error_code=error_code,
        error_message=error_message,
        reasoning_effort=log.reasoning_effort,
        requested_reasoning_effort=log.requested_reasoning_effort,
    )


async def _log_upstream_error(log: _LogFields, exc: ClaudeSidecarError) -> None:
    log_error = claude_sidecar_request_log_error(exc.message, model=log.model)
    await _log_sidecar_request(
        api_key=log.api_key,
        model=log.model,
        started_at=log.started_at,
        status="error",
        error_code=log_error.error_code,
        error_message=log_error.error_message,
        failure_detail=log_error.failure_detail,
        reasoning_effort=log.reasoning_effort,
        requested_reasoning_effort=log.requested_reasoning_effort,
    )


def _failure_of_response(response: JsonValue) -> _UpstreamFailure | None:
    """A 200 Responses object can still carry ``status: failed``."""

    if not is_json_mapping(response) or response.get("status") != "failed":
        return None
    return _failure_from_error(response.get("error"))


def _failure_of_event(event: Mapping[str, JsonValue]) -> _UpstreamFailure:
    if event.get("type") == "error":
        nested = event.get("error")
        return _failure_from_error(nested if is_json_mapping(nested) else event)
    response = event.get("response")
    return _failure_from_error(response.get("error") if is_json_mapping(response) else None)


def _failure_from_error(error: JsonValue) -> _UpstreamFailure:
    code = _UPSTREAM_FAILED_ERROR_CODE
    message = "the upstream reported the response as failed"
    if is_json_mapping(error):
        error_code = error.get("code")
        error_message = error.get("message")
        if isinstance(error_code, str) and error_code.strip():
            code = error_code.strip()
        if isinstance(error_message, str) and error_message.strip():
            message = error_message.strip()
    return _UpstreamFailure(code, message)


def _response_failed_frame(envelope: OpenAIErrorEnvelope) -> str:
    error = envelope.get("error")
    code = error.get("code") if is_json_mapping(error) else None
    message = error.get("message") if is_json_mapping(error) else None
    error_type = error.get("type") if is_json_mapping(error) else None
    event = response_failed_event(
        code if isinstance(code, str) and code else _UPSTREAM_FAILED_ERROR_CODE,
        message if isinstance(message, str) and message else "upstream request failed",
        error_type if isinstance(error_type, str) and error_type else "upstream_error",
    )
    return format_sse_event(cast(Mapping[str, JsonValue], event))
