"""A scriptable fake OpenCode Go upstream, served over real loopback HTTP.

Why a real server rather than a monkeypatched client object: the questions this
task has to answer are wire questions. Which endpoint did the request reach,
which authentication header carried the credential, in what order did the SSE
frames arrive, did the socket actually close when the caller disconnected. A
fake client object answers none of those, because it replaces the very layer
under test. Every assertion built on this fixture is therefore an assertion
about bytes on a socket.

Shape fidelity and its limits
-----------------------------
The served shapes are modelled on evidence recorded in
``codexlb-opencode-go-reuse-r1/report.md`` and on one unauthenticated read-only
probe of ``https://opencode.ai/zen/go/v1/models`` (2026-09-14, 37 ids, echoed in
``LIVE_PROBED_MODEL_IDS``). Three properties are **corroborated third-party
evidence, not a verified contract**, and tests that depend on them say so:

* ``/usage`` returning ``usage.{rolling,weekly,monthly}`` each
  ``{status, percent, resetsAt}`` is read from two independent parsers
  (OmniRoute, ``kartikkabadi/opencode-go-proxy``), never from an authenticated
  capture. Whether those windows are per-model or account-aggregate is unknown.
* ``/messages`` authenticating with ``x-api-key`` rather than a bearer token is
  an unmerged LiteLLM PR author's live-testing claim plus corroborating code.
* The per-model endpoint map drifts, and the OpenCode docs and models.dev
  disagree on four Qwen ids.

``strict_auth_by_endpoint`` exists precisely so a test can pin behavior under
the reported per-endpoint auth rule *and* under the permissive alternative,
rather than silently assuming the reported rule is true.

No credential, host, port, or file path here is read from the ambient
environment. The server binds an ephemeral loopback port and the keys are
literals owned by the test process.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from aiohttp import web

# Verbatim ids from the single unauthenticated probe of
# GET https://opencode.ai/zen/go/v1/models on 2026-09-14. Kept as a literal so a
# test can distinguish "an id the live catalog serves" from one this repo
# invented, without any test making a network call.
LIVE_PROBED_MODEL_IDS: tuple[str, ...] = (
    "minimax-m3",
    "minimax-m2.7",
    "minimax-m2.5",
    "kimi-k3",
    "kimi-k2.7-code",
    "kimi-k2.6",
    "longcat-2.0",
    "kimi-k2.5",
    "glm-5.2",
    "glm-5.3-flash",
    "glm-5.3",
    "glm-5.1",
    "glm-5",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "deepseek-flash",
    "deepseek-v4.1-flash",
    "deepseek-v4-flash-vision-exp",
    "qwen3.7-max",
    "qwen3.8-max",
    "qwen3.8-flash",
    "qwen3.7-plus",
    "qwen3.6-plus",
    "qwen3.5-plus",
    "mimo-v2-pro",
    "mimo-v2-omni",
    "mimo-v2.5-pro",
    "mimo-v2.5",
    "hy4-preview",
    "hy3",
    "hy3-preview",
    "gpt-5.6-luna",
    "grok-4.5",
    "grok-4.6",
    "muse-spark-1.3-contributor",
    "muse-spark-1.2-contributor",
    "omen-alpha",
)

# ``kimi-k2.7`` (bare) is reported rejected on /chat/completions while
# ``kimi-k2.7-code`` works, and it is absent from the probed list above. A test
# that wants "an id the provider does not serve" should use this rather than a
# made-up string, so the negative case matches a real failure mode.
LIVE_PROBED_ABSENT_MODEL_ID = "kimi-k2.7"


@dataclass(frozen=True, slots=True)
class RecordedRequest:
    """One request as the upstream actually received it."""

    method: str
    path: str
    query: Mapping[str, str]
    headers: Mapping[str, str]
    body: Any
    raw_body: bytes

    def header(self, name: str) -> str | None:
        """Case-insensitive single header lookup."""
        lowered = name.lower()
        for key, value in self.headers.items():
            if key.lower() == lowered:
                return value
        return None

    def has_header(self, name: str) -> bool:
        return self.header(name) is not None


@dataclass(slots=True)
class ScriptedResponse:
    """A canned reply that pre-empts the endpoint's default behavior."""

    status: int
    body: Any = None
    headers: Mapping[str, str] = field(default_factory=dict)
    # Consumed once, then the endpoint falls back to its default. ``None``
    # repeats forever, which is what a persistent 429 looks like.
    remaining: int | None = 1


class FakeOpenCodeGoUpstream:
    """A fake ``https://opencode.ai/zen/go/v1`` served on loopback.

    Test-facing knobs are plain attributes rather than a builder because every
    test wants a different two or three of them and a fluent API would hide
    which ones a given test actually pinned.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model_ids: Sequence[str] = LIVE_PROBED_MODEL_IDS,
        strict_auth_by_endpoint: bool = True,
    ) -> None:
        self.api_key = api_key
        self.model_ids = tuple(model_ids)
        # When true, /messages accepts ONLY x-api-key and the OpenAI-shaped
        # endpoints accept ONLY a bearer token, per the reported (not verified)
        # per-endpoint rule. When false, either header is accepted anywhere,
        # which models the permissive alternative.
        self.strict_auth_by_endpoint = strict_auth_by_endpoint

        self.requests: list[RecordedRequest] = []
        self.scripted: dict[str, list[ScriptedResponse]] = {}

        # Content the chat endpoints emit. Overridable per test.
        self.completion_text = "hello from the fake Go upstream"
        self.usage_payload: dict[str, Any] = {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
        }
        self.tool_calls: list[dict[str, Any]] | None = None
        # Seconds of delay injected before each streamed frame, so a
        # cancellation test has a window to disconnect inside.
        self.stream_frame_delay_seconds = 0.0
        # Set when a streaming response was abandoned before its terminator.
        # This is how a disconnect test observes that the upstream socket really
        # went away rather than draining in the background.
        self.stream_disconnected = asyncio.Event()
        self.streams_started = 0
        self.stream_frames_sent = 0

        # ``/usage`` content. ``None`` means "endpoint present but returns the
        # unknown/unsupported shape", which the quota layer must not render as
        # a real number.
        self.usage_windows: dict[str, Any] | None = {
            "rolling": {"status": "ok", "percent": 42, "resetsAt": 1789360000000},
            "weekly": {"status": "ok", "percent": 13, "resetsAt": 1789900000000},
            "monthly": {"status": "ok", "percent": 4, "resetsAt": 1792000000000},
        }

        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._port: int | None = None

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> str:
        app = web.Application()
        app.router.add_get("/v1/models", self._handle_models)
        app.router.add_get("/v1/usage", self._handle_usage)
        app.router.add_post("/v1/chat/completions", self._handle_chat_completions)
        app.router.add_post("/v1/messages", self._handle_messages)
        app.router.add_post("/v1/responses", self._handle_responses)
        # Anything else is a 404 that still gets recorded, so a test can prove a
        # request never reached an endpoint we did not intend to support.
        app.router.add_route("*", "/{tail:.*}", self._handle_unknown)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await self._site.start()
        sockets = self._runner.addresses
        assert sockets, "fake upstream did not bind a port"
        self._port = int(sockets[0][1])
        return self.base_url

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            self._site = None

    @property
    def base_url(self) -> str:
        assert self._port is not None, "fake upstream not started"
        return f"http://127.0.0.1:{self._port}/v1"

    # -- scripting ---------------------------------------------------------

    def script(
        self,
        path: str,
        *,
        status: int,
        body: Any = None,
        headers: Mapping[str, str] | None = None,
        repeat: int | None = 1,
    ) -> None:
        """Queue a canned reply for the next ``repeat`` calls to ``path``."""
        self.scripted.setdefault(path, []).append(
            ScriptedResponse(status=status, body=body, headers=dict(headers or {}), remaining=repeat)
        )

    def _take_scripted(self, path: str) -> ScriptedResponse | None:
        queue = self.scripted.get(path)
        if not queue:
            return None
        entry = queue[0]
        if entry.remaining is None:
            return entry
        entry.remaining -= 1
        if entry.remaining <= 0:
            queue.pop(0)
        return entry

    # -- request inspection ------------------------------------------------

    def requests_for(self, path: str) -> list[RecordedRequest]:
        return [record for record in self.requests if record.path == path]

    @property
    def last_request(self) -> RecordedRequest:
        assert self.requests, "no request reached the fake upstream"
        return self.requests[-1]

    def session_headers_seen(self) -> list[str | None]:
        return [record.header("x-opencode-session") for record in self.requests]

    # -- internals ---------------------------------------------------------

    async def _record(self, request: web.Request) -> RecordedRequest:
        raw = await request.read()
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = None
        record = RecordedRequest(
            method=request.method,
            path=request.path,
            query=dict(request.query),
            headers=dict(request.headers),
            body=parsed,
            raw_body=raw,
        )
        self.requests.append(record)
        return record

    @staticmethod
    def _auth_error() -> web.Response:
        # Byte-for-byte the body the live route returns unauthenticated, per the
        # probe recorded in the reuse report.
        return web.json_response(
            {"type": "error", "error": {"type": "AuthError", "message": "Missing API key."}},
            status=401,
        )

    def _bearer_ok(self, record: RecordedRequest) -> bool:
        value = record.header("authorization") or ""
        return value == f"Bearer {self.api_key}"

    def _api_key_ok(self, record: RecordedRequest) -> bool:
        return record.header("x-api-key") == self.api_key

    def _authorized(self, record: RecordedRequest, *, endpoint: str) -> bool:
        if not self.strict_auth_by_endpoint:
            return self._bearer_ok(record) or self._api_key_ok(record)
        if endpoint == "messages":
            # The reported rule: /messages takes x-api-key. A bearer token alone
            # must fail, otherwise a client that only ever sets Authorization
            # would appear to work here and break against the real provider.
            return self._api_key_ok(record)
        return self._bearer_ok(record)

    def _scripted_response(self, path: str) -> web.Response | None:
        entry = self._take_scripted(path)
        if entry is None:
            return None
        body = entry.body
        if body is None:
            body = {"type": "error", "error": {"type": "ScriptedError", "message": f"scripted {entry.status}"}}
        return web.json_response(body, status=entry.status, headers=dict(entry.headers))

    # -- handlers ----------------------------------------------------------

    async def _handle_models(self, request: web.Request) -> web.StreamResponse:
        record = await self._record(request)
        scripted = self._scripted_response("/v1/models")
        if scripted is not None:
            return scripted
        if not self._authorized(record, endpoint="models"):
            return self._auth_error()
        return web.json_response(
            {
                "object": "list",
                "data": [
                    {"id": model_id, "object": "model", "created": 1789353840, "owned_by": "opencode"}
                    for model_id in self.model_ids
                ],
            }
        )

    async def _handle_usage(self, request: web.Request) -> web.StreamResponse:
        record = await self._record(request)
        scripted = self._scripted_response("/v1/usage")
        if scripted is not None:
            return scripted
        if not self._authorized(record, endpoint="usage"):
            return self._auth_error()
        if self.usage_windows is None:
            # Endpoint reachable, content absent. Distinct from a transport
            # failure and distinct from zero usage, and consumers must keep
            # those three apart.
            return web.json_response({})
        return web.json_response({"usage": self.usage_windows})

    async def _handle_chat_completions(self, request: web.Request) -> web.StreamResponse:
        record = await self._record(request)
        scripted = self._scripted_response("/v1/chat/completions")
        if scripted is not None:
            return scripted
        if not self._authorized(record, endpoint="chat"):
            return self._auth_error()

        body = record.body if isinstance(record.body, dict) else {}
        model = body.get("model")
        if isinstance(model, str) and model not in self.model_ids:
            # Mirrors the live rejection shape reported for unserved ids, so an
            # advertised-but-unserved model fails here instead of appearing to
            # work against a fixture that answers anything.
            return web.json_response(
                {
                    "type": "error",
                    "error": {
                        "type": "InvalidRequestError",
                        "message": f"Model {model} is not supported for format oa-compat",
                    },
                },
                status=400,
            )

        if bool(body.get("stream")):
            return await self._stream_chat(request, model=model, include_usage=self._wants_stream_usage(body))
        message: dict[str, Any] = {"role": "assistant", "content": self.completion_text}
        finish_reason = "stop"
        if self.tool_calls is not None:
            message["content"] = None
            message["tool_calls"] = self.tool_calls
            finish_reason = "tool_calls"
        return web.json_response(
            {
                "id": "chatcmpl-fake-go",
                "object": "chat.completion",
                "created": 1789353840,
                "model": model,
                "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
                "usage": dict(self.usage_payload),
            }
        )

    @staticmethod
    def _wants_stream_usage(body: Mapping[str, Any]) -> bool:
        options = body.get("stream_options")
        return bool(isinstance(options, Mapping) and options.get("include_usage"))

    async def _stream_chat(
        self,
        request: web.Request,
        *,
        model: Any,
        include_usage: bool,
    ) -> web.StreamResponse:
        self.streams_started += 1
        response = web.StreamResponse(
            status=200,
            headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"},
        )
        await response.prepare(request)

        def chunk(delta: dict[str, Any], finish: str | None = None) -> bytes:
            payload = {
                "id": "chatcmpl-fake-go",
                "object": "chat.completion.chunk",
                "created": 1789353840,
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            return f"data: {json.dumps(payload)}\n\n".encode()

        frames: list[bytes] = [chunk({"role": "assistant", "content": ""})]
        if self.tool_calls is not None:
            frames.append(chunk({"tool_calls": self.tool_calls}))
            frames.append(chunk({}, finish="tool_calls"))
        else:
            for piece in self.completion_text.split(" "):
                frames.append(chunk({"content": f"{piece} "}))
            frames.append(chunk({}, finish="stop"))
        if include_usage:
            trailing = {
                "id": "chatcmpl-fake-go",
                "object": "chat.completion.chunk",
                "created": 1789353840,
                "model": model,
                "choices": [],
                "usage": dict(self.usage_payload),
            }
            frames.append(f"data: {json.dumps(trailing)}\n\n".encode())
        frames.append(b"data: [DONE]\n\n")

        try:
            for frame in frames:
                if self.stream_frame_delay_seconds:
                    await asyncio.sleep(self.stream_frame_delay_seconds)
                await response.write(frame)
                self.stream_frames_sent += 1
            await response.write_eof()
        except (ConnectionResetError, asyncio.CancelledError, OSError):
            # The caller went away mid-stream. Record it and let the exception
            # end this handler; a test asserting on disconnect propagation reads
            # ``stream_disconnected``.
            self.stream_disconnected.set()
            raise
        return response

    async def _handle_messages(self, request: web.Request) -> web.StreamResponse:
        record = await self._record(request)
        scripted = self._scripted_response("/v1/messages")
        if scripted is not None:
            return scripted
        if not self._authorized(record, endpoint="messages"):
            return self._auth_error()
        body = record.body if isinstance(record.body, dict) else {}
        return web.json_response(
            {
                "id": "msg_fake_go",
                "type": "message",
                "role": "assistant",
                "model": body.get("model"),
                "content": [{"type": "text", "text": self.completion_text}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 11, "output_tokens": 7},
            }
        )

    async def _handle_responses(self, request: web.Request) -> web.StreamResponse:
        record = await self._record(request)
        scripted = self._scripted_response("/v1/responses")
        if scripted is not None:
            return scripted
        if not self._authorized(record, endpoint="responses"):
            return self._auth_error()
        body = record.body if isinstance(record.body, dict) else {}
        return web.json_response(
            {
                "id": "resp_fake_go",
                "object": "response",
                "status": "completed",
                "model": body.get("model"),
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": self.completion_text}],
                    }
                ],
                "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
            }
        )

    async def _handle_unknown(self, request: web.Request) -> web.StreamResponse:
        await self._record(request)
        return web.json_response({"error": "not found"}, status=404)


@asynccontextmanager
async def fake_opencode_go_upstream(
    *,
    api_key: str = "sk-fake-go-test-key",
    model_ids: Sequence[str] = LIVE_PROBED_MODEL_IDS,
    strict_auth_by_endpoint: bool = True,
) -> AsyncIterator[FakeOpenCodeGoUpstream]:
    upstream = FakeOpenCodeGoUpstream(
        api_key=api_key,
        model_ids=model_ids,
        strict_auth_by_endpoint=strict_auth_by_endpoint,
    )
    await upstream.start()
    try:
        yield upstream
    finally:
        await upstream.stop()


def build_sse_reader() -> Callable[[bytes], list[dict[str, Any]]]:
    """Return a parser for ``data:`` frames, skipping the ``[DONE]`` sentinel."""

    def parse(body: bytes | str) -> list[dict[str, Any]]:
        text = body.decode("utf-8") if isinstance(body, bytes) else body
        frames: list[dict[str, Any]] = []
        for line in text.splitlines():
            if not line.startswith("data: "):
                continue
            payload = line.removeprefix("data: ")
            if payload == "[DONE]":
                continue
            frames.append(json.loads(payload))
        return frames

    return parse
