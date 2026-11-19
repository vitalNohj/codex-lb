"""A restart on a systemd-held socket finishes streams and queues new requests.

The test plays systemd: it owns the listening socket for the whole restart
and starts each server process with it on fd 3 (``LISTEN_PID``/``LISTEN_FDS``).
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest

pytestmark = pytest.mark.integration

_READY_TIMEOUT_SECONDS = 15.0
_STREAM_CHUNKS = 20
_CHUNK_INTERVAL_SECONDS = 0.1
# Uvicorn re-raises SIGTERM after a graceful shutdown; systemd counts that as
# a clean stop.
_GRACEFUL_EXIT_CODES = (0, -signal.SIGTERM)


def _listening_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    return sock


@asynccontextmanager
async def _server_on(
    listener: socket.socket,
    *,
    drain_timeout_seconds: float,
    no_handoff: bool = False,
) -> AsyncIterator[asyncio.subprocess.Process]:
    listener_fd = listener.fileno()

    def _place_socket_on_fd3() -> None:
        os.dup2(listener_fd, 3)

    args = [
        "--drain-timeout-seconds",
        str(drain_timeout_seconds),
        "--stream-chunks",
        str(_STREAM_CHUNKS),
        "--chunk-interval-seconds",
        str(_CHUNK_INTERVAL_SECONDS),
    ]
    if no_handoff:
        args.append("--no-handoff")
    env = {key: value for key, value in os.environ.items() if not key.startswith("LISTEN_")}
    env["LISTEN_FDS"] = "1"
    # systemd addresses the descriptors to the service's own pid. ``exec``
    # keeps the shell's pid, so ``$$`` is the server's pid.
    process = await asyncio.create_subprocess_exec(
        "/bin/sh",
        "-c",
        'LISTEN_PID=$$ exec "$0" -m tests.fixtures.socket_handoff_server "$@"',
        sys.executable,
        *args,
        env=env,
        preexec_fn=_place_socket_on_fd3,
        pass_fds=(3,),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        yield process
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def _wait_until_serving(base_url: str, process: asyncio.subprocess.Process) -> int:
    deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
    async with httpx.AsyncClient(timeout=1.0) as client:
        while time.monotonic() < deadline:
            if process.returncode is not None:
                output = await process.stdout.read() if process.stdout is not None else b""
                raise AssertionError(f"server exited early: {output.decode(errors='replace')}")
            try:
                response = await client.get(f"{base_url}/whoami")
                payload = response.json()
                if response.status_code == 200 and payload["pid"] == process.pid:
                    return process.pid
            except (httpx.HTTPError, ValueError):
                pass
            await asyncio.sleep(0.05)
    raise AssertionError("server did not start serving")


async def _read_stream(client: httpx.AsyncClient, url: str, first_chunk: asyncio.Event) -> list[str]:
    events: list[str] = []
    async with client.stream("GET", url) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                events.append(line.removeprefix("data: "))
                first_chunk.set()
    return events


@pytest.mark.asyncio
async def test_restart_on_held_socket_finishes_stream_and_queues_new_request() -> None:
    listener = _listening_socket()
    base_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
    try:
        async with _server_on(listener, drain_timeout_seconds=10.0) as old:
            old_pid = await _wait_until_serving(base_url, old)
            async with httpx.AsyncClient(timeout=30.0) as stream_client:
                first_chunk = asyncio.Event()
                stream_task = asyncio.create_task(_read_stream(stream_client, f"{base_url}/v1/stream", first_chunk))
                await asyncio.wait_for(first_chunk.wait(), timeout=5)

                old.send_signal(signal.SIGTERM)
                # Give the old process time to commit its drain and stop accepting.
                await asyncio.sleep(0.3)
                async with httpx.AsyncClient(timeout=30.0) as late_client:
                    late_task = asyncio.create_task(late_client.get(f"{base_url}/whoami"))
                    await asyncio.sleep(0.3)
                    assert not late_task.done(), "a request during the drain must wait, not fail"

                    events = await asyncio.wait_for(stream_task, timeout=15)
                    assert await asyncio.wait_for(old.wait(), timeout=15) in _GRACEFUL_EXIT_CODES

                    # The old process finished its whole stream before exiting.
                    assert events[-1] == "[DONE]"
                    chunks = [json.loads(event) for event in events[:-1]]
                    assert [chunk["index"] for chunk in chunks] == list(range(_STREAM_CHUNKS))
                    assert {chunk["pid"] for chunk in chunks} == {old_pid}
                    assert not late_task.done()

                    # systemd starts the next process on the same socket; it
                    # serves the request that waited in the kernel queue.
                    async with _server_on(listener, drain_timeout_seconds=10.0) as new:
                        late = await asyncio.wait_for(late_task, timeout=_READY_TIMEOUT_SECONDS)
                        assert late.status_code == 200
                        assert late.json() == {"pid": new.pid, "draining": False}
                        new.send_signal(signal.SIGTERM)
                        assert await asyncio.wait_for(new.wait(), timeout=15) in _GRACEFUL_EXIT_CODES
    finally:
        listener.close()


@pytest.mark.asyncio
async def test_without_handoff_a_request_during_the_drain_is_refused() -> None:
    """The behavior the handoff replaces: the draining process answers 503."""
    listener = _listening_socket()
    base_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
    try:
        async with _server_on(listener, drain_timeout_seconds=10.0, no_handoff=True) as old:
            await _wait_until_serving(base_url, old)
            async with httpx.AsyncClient(timeout=30.0) as stream_client:
                first_chunk = asyncio.Event()
                stream_task = asyncio.create_task(_read_stream(stream_client, f"{base_url}/v1/stream", first_chunk))
                await asyncio.wait_for(first_chunk.wait(), timeout=5)

                old.send_signal(signal.SIGTERM)
                await asyncio.sleep(0.3)
                async with httpx.AsyncClient(timeout=5.0) as late_client:
                    late = await late_client.get(f"{base_url}/whoami")
                assert late.status_code == 503
                assert late.json()["error"]["message"] == "Server is draining"
                assert late.headers["retry-after"] == "5"
                await asyncio.wait_for(stream_task, timeout=15)
    finally:
        listener.close()
