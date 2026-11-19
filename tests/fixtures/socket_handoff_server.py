"""Process fixture: one codex-lb-style server on a systemd-style inherited socket.

The test holds the listening socket (as systemd does) and starts this module
with ``LISTEN_PID``/``LISTEN_FDS`` and the socket on fd 3.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Sequence

import uvicorn

from app.core import shutdown as shutdown_state
from app.core.middleware.inflight import InFlightMiddleware
from app.core.server import GracefulDrainServer
from app.core.socket_activation import inherited_listen_socket


class _App:
    def __init__(self, *, stream_chunks: int, chunk_interval_seconds: float) -> None:
        self._stream_chunks = stream_chunks
        self._chunk_interval_seconds = chunk_interval_seconds

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] != "http":
            return
        path = scope.get("path", "")
        if path == "/v1/stream":
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")],
                }
            )
            for index in range(self._stream_chunks):
                chunk = json.dumps({"pid": os.getpid(), "index": index}, separators=(",", ":"))
                await send({"type": "http.response.body", "body": f"data: {chunk}\n\n".encode(), "more_body": True})
                await asyncio.sleep(self._chunk_interval_seconds)
            await send({"type": "http.response.body", "body": b"data: [DONE]\n\n", "more_body": False})
            return
        body = json.dumps(
            {"pid": os.getpid(), "draining": shutdown_state.is_draining()},
            separators=(",", ":"),
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--drain-timeout-seconds", required=True, type=float)
    parser.add_argument("--stream-chunks", type=int, default=20)
    parser.add_argument("--chunk-interval-seconds", type=float, default=0.1)
    parser.add_argument(
        "--no-handoff",
        action="store_true",
        help="Serve the inherited socket but keep accepting during the drain (the old behavior).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    shutdown_state.reset()
    listen_socket = inherited_listen_socket()
    if listen_socket is None:
        raise SystemExit("no socket from the launcher")
    app = InFlightMiddleware(_App(stream_chunks=args.stream_chunks, chunk_interval_seconds=args.chunk_interval_seconds))
    config = uvicorn.Config(
        app,
        lifespan="off",
        log_level="warning",
        timeout_graceful_shutdown=args.drain_timeout_seconds,
    )
    server = GracefulDrainServer(
        config,
        drain_timeout_seconds=args.drain_timeout_seconds,
        stop_accepting_on_drain=not args.no_handoff,
    )
    server.run(sockets=[listen_socket])
    return 0 if server.started else 3


if __name__ == "__main__":
    raise SystemExit(main())
