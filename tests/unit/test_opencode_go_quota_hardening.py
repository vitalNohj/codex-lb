"""Regressions for two PR 45 review findings.

1. **Critical** - the usage response body was consumed with ``response.text()``
   before any size bound, so an upstream (hostile, misconfigured, or a captive
   portal) could stream an unbounded body straight into memory. A quota poll
   must never let a remote party decide how much this process allocates.

2. **High** - the single-flight producer ran in the first caller's task. If that
   caller was cancelled (client disconnect, dashboard navigation), the in-flight
   request died and every other waiter was cancelled with it, even though they
   were still waiting and healthy.

Both are exercised against local fakes: streaming fixtures with known byte
counts, and real ``asyncio`` cancellation. No network, no credentials.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

import pytest

import app.core.clients.opencode_go as opencode_go_client
from app.core.clients.opencode_go import (
    DEFAULT_OPENCODE_GO_BASE_URL,
    OpenCodeGoClient,
    OpenCodeGoConfig,
    OpenCodeGoUnavailableError,
)
from app.modules.opencode_go.service import OpenCodeGoQuotaCache

pytestmark = pytest.mark.unit

# Resolved at runtime with a fallback rather than imported as a required symbol.
#
# These tests must *collect and fail on behaviour* against the pre-fix client. A
# hard `from ... import MAX_USAGE_RESPONSE_BYTES` turned the pre-fix run into a
# collection ImportError, which proves only that a constant is missing - not that
# the old reader was unbounded. With this fallback the byte-limit assertions run
# against either version, and on the unfixed one they fail because the body is
# read in full.
MAX_USAGE_RESPONSE_BYTES = getattr(opencode_go_client, "MAX_USAGE_RESPONSE_BYTES", 1024 * 1024)

# Kept small on purpose: the over-read is detected by the recorded byte count and
# the exhausted flag, not by allocating anything large. The fixtures below offer
# a few multiples of the cap using repeated references, so an unbounded reader is
# caught without a big allocation.
_CHUNK_BYTES = 64 * 1024

_FAKE_KEY = "sk-oc-go-hardening-000000"


def _config(**overrides) -> OpenCodeGoConfig:
    values = {
        "enabled": True,
        "base_url": DEFAULT_OPENCODE_GO_BASE_URL,
        "api_key": _FAKE_KEY,
        "connect_timeout_seconds": 5.0,
        "request_timeout_seconds": 10.0,
    }
    values.update(overrides)
    return OpenCodeGoConfig(**values)


class _StreamingContent:
    """Yields chunks and records how many bytes were actually pulled.

    Models the decompressed/chunked stream: there is no ``Content-Length`` to
    consult, so the only real defence is bounding what we read.
    """

    def __init__(self, chunks: list[bytes], *, total_available: int | None = None) -> None:
        self._chunks = chunks
        self.bytes_yielded = 0
        self.exhausted = False
        self.total_available = total_available if total_available is not None else sum(len(c) for c in chunks)

    async def iter_chunked(self, size: int):
        for chunk in self._chunks:
            self.bytes_yielded += len(chunk)
            yield chunk
        self.exhausted = True

    async def read(self, n: int = -1) -> bytes:
        raise AssertionError("unbounded read() must not be used for the usage body")


class _StreamingResponse:
    """A response exposing **both** the streaming and buffering interfaces.

    ``text()`` is implemented rather than raising, so the pre-fix client - which
    calls it - still runs and is judged on what it does: it drains the fixture
    completely, so ``bytes_yielded`` reaches the full offered size and
    ``exhausted`` becomes true, failing the bound assertions. A fake that simply
    refused ``text()`` would fail on the missing API instead of on the
    behaviour, which is not a reproduction.
    """

    def __init__(self, status: int, content: _StreamingContent, headers: dict | None = None) -> None:
        self.status = status
        self.content = content
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def text(self) -> str:
        parts = []
        async for chunk in self.content.iter_chunked(_CHUNK_BYTES):
            parts.append(chunk)
        return b"".join(parts).decode("utf-8", errors="replace")


class _StreamingSession:
    def __init__(self, response: _StreamingResponse) -> None:
        self._response = response

    def get(self, url, headers=None, timeout=None):
        return self._response


def _patch_session(monkeypatch, response: _StreamingResponse):
    import contextlib

    session = _StreamingSession(response)

    @contextlib.asynccontextmanager
    async def _lease():
        yield session

    monkeypatch.setattr("app.core.clients.opencode_go.lease_http_session", _lease)


class TestBoundedBodyConsumption:
    @pytest.mark.asyncio
    async def test_small_json_body_still_parses(self, monkeypatch):
        content = _StreamingContent([b'{"usage": {"rolling":', b' {"status": "ok", "percent": 5}}}'])
        _patch_session(monkeypatch, _StreamingResponse(200, content))

        body = await OpenCodeGoClient(_config()).fetch_usage()

        assert body == {"usage": {"rolling": {"status": "ok", "percent": 5}}}

    @pytest.mark.asyncio
    async def test_oversized_body_is_rejected_without_buffering_it_all(self, monkeypatch):
        """The whole point: stop reading, do not allocate the entire stream.

        The fixture offers several times the cap. A correct implementation stops
        shortly after crossing it; the pre-fix ``response.text()`` path consumed
        every byte, which the recorded counter and ``exhausted`` flag detect.
        """
        chunk = b"x" * _CHUNK_BYTES
        chunk_count = (MAX_USAGE_RESPONSE_BYTES // len(chunk)) * 4
        content = _StreamingContent([chunk] * chunk_count)
        _patch_session(monkeypatch, _StreamingResponse(200, content))

        with pytest.raises(OpenCodeGoUnavailableError) as excinfo:
            await OpenCodeGoClient(_config()).fetch_usage()

        assert content.bytes_yielded <= MAX_USAGE_RESPONSE_BYTES + len(chunk)
        assert content.bytes_yielded < content.total_available
        assert not content.exhausted
        assert "too large" in str(excinfo.value).lower()

    @pytest.mark.asyncio
    async def test_oversized_error_body_is_also_bounded(self, monkeypatch):
        """A 500 with an enormous HTML error page must not be buffered either."""
        chunk = b"<p>error</p>" * 4096
        chunk_count = (MAX_USAGE_RESPONSE_BYTES // len(chunk)) * 3
        content = _StreamingContent([chunk] * chunk_count)
        _patch_session(monkeypatch, _StreamingResponse(500, content))

        with pytest.raises(OpenCodeGoUnavailableError):
            await OpenCodeGoClient(_config()).fetch_usage()

        assert content.bytes_yielded <= MAX_USAGE_RESPONSE_BYTES + len(chunk)
        assert not content.exhausted

    @pytest.mark.asyncio
    async def test_oversize_diagnostic_is_sanitized_and_bounded(self, monkeypatch):
        """The size error must not echo the body or leak the credential."""
        secret = _FAKE_KEY
        chunk = f"Authorization: Bearer {secret} ".encode() * 4096
        chunk_count = (MAX_USAGE_RESPONSE_BYTES // len(chunk)) * 3
        content = _StreamingContent([chunk] * chunk_count)
        _patch_session(monkeypatch, _StreamingResponse(200, content))

        with pytest.raises(OpenCodeGoUnavailableError) as excinfo:
            await OpenCodeGoClient(_config()).fetch_usage()

        message = str(excinfo.value)
        assert secret not in message
        assert len(message) < 300

    @pytest.mark.asyncio
    async def test_body_at_the_limit_is_accepted(self, monkeypatch):
        """The bound rejects what exceeds it, not what merely approaches it."""
        padding = MAX_USAGE_RESPONSE_BYTES - 64
        payload = b'{"usage": {}, "_pad": "' + (b"p" * padding) + b'"}'
        assert len(payload) <= MAX_USAGE_RESPONSE_BYTES
        content = _StreamingContent([payload])
        _patch_session(monkeypatch, _StreamingResponse(200, content))

        body = await OpenCodeGoClient(_config()).fetch_usage()

        assert body["usage"] == {}

    @pytest.mark.asyncio
    async def test_declared_content_length_over_the_cap_short_circuits(self, monkeypatch):
        """When upstream declares an oversized length, do not read the body at all."""
        content = _StreamingContent([b"x" * 1024])
        response = _StreamingResponse(
            200,
            content,
            headers={"Content-Length": str(MAX_USAGE_RESPONSE_BYTES * 10)},
        )
        _patch_session(monkeypatch, response)

        with pytest.raises(OpenCodeGoUnavailableError):
            await OpenCodeGoClient(_config()).fetch_usage()

        assert content.bytes_yielded == 0

    @pytest.mark.asyncio
    async def test_exact_boundary_one_byte_over_is_rejected(self, monkeypatch):
        """Exactly at the cap passes; exactly one byte over is rejected."""
        over = b"y" * (MAX_USAGE_RESPONSE_BYTES + 1)
        content = _StreamingContent([over])
        _patch_session(monkeypatch, _StreamingResponse(200, content))

        with pytest.raises(OpenCodeGoUnavailableError):
            await OpenCodeGoClient(_config()).fetch_usage()

    @pytest.mark.asyncio
    async def test_expanded_stream_with_small_declared_wire_length_is_bounded(self, monkeypatch):
        """Counting happens on what the consumer receives, not the wire length.

        **Scope of this test, stated precisely:** the fixture yields already
        expanded bytes while advertising a small compressed ``Content-Length``.
        That proves the *consumer* counts decoded bytes and ignores a small
        declared length - it does **not** exercise aiohttp's decompressor, and
        so says nothing about peak allocation inside the transport. The real
        transport behaviour is covered by the loopback test in
        ``TestRealTransportCompression``.
        """
        import gzip

        raw = b"z" * (MAX_USAGE_RESPONSE_BYTES * 3)
        wire = gzip.compress(raw)
        assert len(wire) < MAX_USAGE_RESPONSE_BYTES  # small on the wire

        content = _StreamingContent([raw[i : i + _CHUNK_BYTES] for i in range(0, len(raw), _CHUNK_BYTES)])
        response = _StreamingResponse(
            200,
            content,
            headers={"Content-Encoding": "gzip", "Content-Length": str(len(wire))},
        )
        _patch_session(monkeypatch, response)

        with pytest.raises(OpenCodeGoUnavailableError):
            await OpenCodeGoClient(_config()).fetch_usage()

        assert not content.exhausted
        assert content.bytes_yielded <= MAX_USAGE_RESPONSE_BYTES + _CHUNK_BYTES

    @pytest.mark.asyncio
    async def test_understated_content_length_does_not_authorize_an_over_read(self, monkeypatch):
        """A lying ``Content-Length`` must not raise the effective ceiling."""
        chunk = b"w" * _CHUNK_BYTES
        chunk_count = (MAX_USAGE_RESPONSE_BYTES // len(chunk)) * 3
        content = _StreamingContent([chunk] * chunk_count)
        response = _StreamingResponse(200, content, headers={"Content-Length": "12"})
        _patch_session(monkeypatch, response)

        with pytest.raises(OpenCodeGoUnavailableError):
            await OpenCodeGoClient(_config()).fetch_usage()

        assert not content.exhausted

    @pytest.mark.asyncio
    async def test_absent_content_length_chunked_stream_is_still_bounded(self, monkeypatch):
        """Chunked transfer has no length header at all; the cap still applies."""
        chunk = b"c" * _CHUNK_BYTES
        chunk_count = (MAX_USAGE_RESPONSE_BYTES // len(chunk)) * 3
        content = _StreamingContent([chunk] * chunk_count)
        response = _StreamingResponse(200, content, headers={"Transfer-Encoding": "chunked"})
        _patch_session(monkeypatch, response)

        with pytest.raises(OpenCodeGoUnavailableError):
            await OpenCodeGoClient(_config()).fetch_usage()

        assert not content.exhausted

    @pytest.mark.asyncio
    async def test_transport_failure_mid_stream_is_unavailable(self, monkeypatch):
        """A disconnect part-way through the body is a transport error."""

        class _FailingContent(_StreamingContent):
            async def iter_chunked(self, size: int):
                yield b'{"usage":'
                raise ConnectionResetError("peer went away")

        _patch_session(monkeypatch, _StreamingResponse(200, _FailingContent([])))

        with pytest.raises(OpenCodeGoUnavailableError):
            await OpenCodeGoClient(_config()).fetch_usage()


class TestSingleFlightCancellation:
    """The cache owns the producer; no single caller can kill it."""

    @pytest.mark.asyncio
    async def test_first_caller_cancellation_does_not_cancel_other_waiters(self):
        cache = OpenCodeGoQuotaCache(ttl_seconds=300.0)
        config = _config()
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def _fetch():
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return "result"

        first = asyncio.create_task(cache.fetch_single_flight(config, _fetch))
        await started.wait()
        second = asyncio.create_task(cache.fetch_single_flight(config, _fetch))
        await asyncio.sleep(0)

        # The first caller goes away mid-flight - a dashboard tab closing.
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first

        release.set()
        # The survivor must still get its answer from the same upstream call.
        assert await asyncio.wait_for(second, timeout=2) == "result"
        assert calls == 1

    @pytest.mark.asyncio
    async def test_all_callers_cancelled_does_not_wedge_the_cache(self):
        cache = OpenCodeGoQuotaCache(ttl_seconds=300.0)
        config = _config()
        started = asyncio.Event()
        release = asyncio.Event()

        async def _fetch():
            started.set()
            await release.wait()
            return "first"

        task = asyncio.create_task(cache.fetch_single_flight(config, _fetch))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        await asyncio.sleep(0.05)

        # A later caller must be able to fetch again rather than joining a dead
        # or already-consumed in-flight entry.
        async def _fetch_again():
            return "second"

        assert await cache.fetch_single_flight(config, _fetch_again) in {"first", "second"}

    @pytest.mark.asyncio
    async def test_producer_failure_propagates_to_every_waiter(self):
        cache = OpenCodeGoQuotaCache(ttl_seconds=300.0)
        config = _config()
        started = asyncio.Event()
        release = asyncio.Event()

        async def _fetch():
            started.set()
            await release.wait()
            raise RuntimeError("upstream exploded")

        first = asyncio.create_task(cache.fetch_single_flight(config, _fetch))
        await started.wait()
        second = asyncio.create_task(cache.fetch_single_flight(config, _fetch))
        await asyncio.sleep(0)
        release.set()

        for task in (first, second):
            with pytest.raises(RuntimeError, match="upstream exploded"):
                await task

    @pytest.mark.asyncio
    async def test_no_task_is_leaked_after_completion(self):
        """The producer task must not outlive the request it served."""
        cache = OpenCodeGoQuotaCache(ttl_seconds=300.0)
        config = _config()
        before = len(asyncio.all_tasks())

        async def _fetch():
            await asyncio.sleep(0)
            return "done"

        assert await cache.fetch_single_flight(config, _fetch) == "done"
        await asyncio.sleep(0.05)

        assert len(asyncio.all_tasks()) <= before

    @pytest.mark.asyncio
    async def test_reset_during_an_inflight_request_does_not_warn_or_leak(self, recwarn):
        """``reset()`` detaches a live producer; it must not leave a noisy task.

        A settings change calls ``reset()`` while a request may be in flight. The
        detached producer's failure would otherwise surface as an
        "exception was never retrieved" destructor warning.
        """
        cache = OpenCodeGoQuotaCache(ttl_seconds=300.0)
        config = _config()
        started = asyncio.Event()
        release = asyncio.Event()

        async def _fetch():
            started.set()
            await release.wait()
            raise RuntimeError("upstream exploded after reset")

        waiter = asyncio.create_task(cache.fetch_single_flight(config, _fetch))
        await started.wait()

        cache.reset()
        release.set()
        with pytest.raises(RuntimeError):
            await waiter
        await asyncio.sleep(0.05)

        assert not [w for w in recwarn.list if "never retrieved" in str(w.message)]

    @pytest.mark.asyncio
    async def test_reset_permanently_invalidates_a_held_producers_late_success(self):
        """A producer in flight across ``reset()`` must not repopulate the cache.

        ``reset()`` is what a settings change calls. The detached producer's
        closure still holds the *old* credential-derived config, so if its late
        ``record_success`` lands it resurrects state the operator just
        invalidated - and a subsequent read could serve the previous
        subscription's numbers.
        """
        cache = OpenCodeGoQuotaCache(ttl_seconds=300.0)
        config = _config(api_key="key-old")
        started = asyncio.Event()
        release = asyncio.Event()

        async def _fetch():
            started.set()
            await release.wait()
            # The stale producer tries to write its result after the reset.
            return cache.record_success(config, "stale-quota")

        waiter = asyncio.create_task(cache.fetch_single_flight(config, _fetch))
        await started.wait()

        cache.reset()
        release.set()
        with contextlib.suppress(BaseException):
            await waiter
        await asyncio.sleep(0.05)

        # The invalidated state must stay invalidated.
        assert cache.last_good(config) is None
        assert cache.fresh(config, now=time.monotonic()) is None

    @pytest.mark.asyncio
    async def test_reset_permanently_invalidates_a_held_producers_late_failure(self):
        """Same invariant for the failure path."""
        cache = OpenCodeGoQuotaCache(ttl_seconds=300.0, failure_ttl_seconds=300.0)
        config = _config(api_key="key-old")
        started = asyncio.Event()
        release = asyncio.Event()

        async def _fetch():
            started.set()
            await release.wait()
            cache.record_failure(config, "unavailable", "stale failure")
            raise RuntimeError("late failure")

        waiter = asyncio.create_task(cache.fetch_single_flight(config, _fetch))
        await started.wait()

        cache.reset()
        release.set()
        with contextlib.suppress(BaseException):
            await waiter
        await asyncio.sleep(0.05)

        assert cache.recent_failure(config, now=time.monotonic()) is None

    @pytest.mark.asyncio
    async def test_a_rekey_after_reset_does_not_see_the_old_producers_result(self):
        """End-to-end shape of the defect: reset, rekey, then the old fetch lands."""
        cache = OpenCodeGoQuotaCache(ttl_seconds=300.0)
        old_config = _config(api_key="key-old")
        new_config = _config(api_key="key-new")
        started = asyncio.Event()
        release = asyncio.Event()

        async def _old_fetch():
            started.set()
            await release.wait()
            return cache.record_success(old_config, "old-subscription-quota")

        stale = asyncio.create_task(cache.fetch_single_flight(old_config, _old_fetch))
        await started.wait()

        # Operator swaps the key: settings change -> reset.
        cache.reset()

        async def _new_fetch():
            return cache.record_success(new_config, "new-subscription-quota")

        assert await cache.fetch_single_flight(new_config, _new_fetch) is not None

        # Now the stale producer finally completes.
        release.set()
        with contextlib.suppress(BaseException):
            await stale
        await asyncio.sleep(0.05)

        # The new key's entry must survive, and the old key must have none.
        assert cache.last_good(old_config) is None
        new_entry = cache.last_good(new_config)
        assert new_entry is not None and new_entry.quota == "new-subscription-quota"

    @pytest.mark.asyncio
    async def test_reset_leaves_no_stranded_producer_task(self):
        """Invalidation must not come at the cost of a leaked task."""
        cache = OpenCodeGoQuotaCache(ttl_seconds=300.0)
        config = _config()
        started = asyncio.Event()
        release = asyncio.Event()
        before = len(asyncio.all_tasks())

        async def _fetch():
            started.set()
            await release.wait()
            return "done"

        waiter = asyncio.create_task(cache.fetch_single_flight(config, _fetch))
        await started.wait()
        cache.reset()
        release.set()
        with contextlib.suppress(BaseException):
            await waiter
        await asyncio.sleep(0.05)

        assert len(asyncio.all_tasks()) <= before

    @pytest.mark.asyncio
    async def test_reset_does_not_break_cancellation_isolation_for_live_callers(self):
        """The earlier cancellation guarantee must survive this fix."""
        cache = OpenCodeGoQuotaCache(ttl_seconds=300.0)
        config = _config()
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def _fetch():
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return "result"

        first = asyncio.create_task(cache.fetch_single_flight(config, _fetch))
        await started.wait()
        second = asyncio.create_task(cache.fetch_single_flight(config, _fetch))
        await asyncio.sleep(0)

        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first

        release.set()
        assert await asyncio.wait_for(second, timeout=2) == "result"
        assert calls == 1

    @pytest.mark.asyncio
    async def test_a_different_config_never_joins_the_inflight_request(self):
        """Config isolation survives the producer-ownership change."""
        cache = OpenCodeGoQuotaCache(ttl_seconds=300.0)
        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow():
            started.set()
            await release.wait()
            return "key-a"

        async def _other():
            return "key-b"

        first = asyncio.create_task(cache.fetch_single_flight(_config(api_key="key-a"), _slow))
        await started.wait()
        # A re-keyed subscription must not receive the previous key's answer.
        assert await cache.fetch_single_flight(_config(api_key="key-b"), _other) == "key-b"

        release.set()
        assert await first == "key-a"


class TestRealTransportCompression:
    """Real loopback HTTP, real aiohttp transport, real gzip decompression.

    The fake-based test above proves only that the *consumer* counts decoded
    bytes. These add real transport: an oversize gzip body and an oversize
    chunked body are rejected end to end, and a small gzip body still parses.

    **Scope limit.** Rejecting at the endpoint says nothing about peak
    allocation *inside* the decompressor; those are independent properties. On
    the pinned ``aiohttp 3.14.3``, ``DeflateBuffer.feed_data`` passes
    ``max_length = max(self._max_decompress_size, low_water)`` (default
    ``max_decompress_size = 262144``) to ``decompress_sync``, so it yields
    bounded slices and leaves the rest behind ``data_available`` - 1 MiB of
    ``b"z"`` gzips to 1051 bytes and produces one 262144-byte chunk. That is a
    property of this pinned version, established by reading and exercising the
    parser, not something these tests prove; another version or a ``low_water``
    at/above ``sys.maxsize`` (which makes ``max_length`` 0, i.e. unbounded)
    could differ.

    Fixtures are modest (a few multiples of a deliberately small cap, patched
    for the test) so nothing here is resource exhausting.
    """

    @pytest.fixture(autouse=True)
    def _real_http_session(self, monkeypatch):
        """Lease a genuine ``aiohttp`` session for the duration of the test.

        The production lease helper expects the app lifespan to have created the
        shared client. These tests run outside it, so a real session is created
        here - real transport is the entire point, so it must not be faked.
        """
        import contextlib

        import aiohttp

        @contextlib.asynccontextmanager
        async def _lease():
            async with aiohttp.ClientSession() as session:
                yield session

        monkeypatch.setattr("app.core.clients.opencode_go.lease_http_session", _lease)

    @pytest.mark.asyncio
    async def test_gzip_response_is_bounded_by_decoded_size_over_real_transport(self, monkeypatch):
        import gzip

        from aiohttp import web
        from aiohttp.test_utils import TestServer

        # Small cap so the fixture stays tiny while still crossing it.
        small_cap = 256 * 1024
        monkeypatch.setattr(opencode_go_client, "MAX_USAGE_RESPONSE_BYTES", small_cap)

        raw = b"z" * (small_cap * 4)
        wire = gzip.compress(raw)
        assert len(wire) < small_cap, "compressed payload must be small on the wire"

        async def handler(request):
            return web.Response(
                body=wire,
                headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
            )

        app = web.Application()
        app.router.add_get("/usage", handler)
        server = TestServer(app)
        await server.start_server()
        try:
            config = _config(base_url=str(server.make_url("")).rstrip("/"))
            with pytest.raises(OpenCodeGoUnavailableError) as excinfo:
                await OpenCodeGoClient(config).fetch_usage()
            assert "too large" in str(excinfo.value).lower()
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_small_gzip_response_still_parses_over_real_transport(self, monkeypatch):
        """Control: compression itself is not what triggers rejection."""
        import gzip

        from aiohttp import web
        from aiohttp.test_utils import TestServer

        monkeypatch.setattr(opencode_go_client, "MAX_USAGE_RESPONSE_BYTES", 256 * 1024)
        wire = gzip.compress(b'{"usage": {"rolling": {"status": "ok", "percent": 7}}}')

        async def handler(request):
            return web.Response(
                body=wire,
                headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
            )

        app = web.Application()
        app.router.add_get("/usage", handler)
        server = TestServer(app)
        await server.start_server()
        try:
            config = _config(base_url=str(server.make_url("")).rstrip("/"))
            body = await OpenCodeGoClient(config).fetch_usage()
            assert body == {"usage": {"rolling": {"status": "ok", "percent": 7}}}
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_uncompressed_oversize_response_is_bounded_over_real_transport(self, monkeypatch):
        from aiohttp import web
        from aiohttp.test_utils import TestServer

        small_cap = 256 * 1024
        monkeypatch.setattr(opencode_go_client, "MAX_USAGE_RESPONSE_BYTES", small_cap)

        async def handler(request):
            response = web.StreamResponse(headers={"Content-Type": "application/json"})
            await response.prepare(request)
            chunk = b"q" * 32 * 1024
            for _ in range((small_cap // len(chunk)) * 3):
                await response.write(chunk)
            await response.write_eof()
            return response

        app = web.Application()
        app.router.add_get("/usage", handler)
        server = TestServer(app)
        await server.start_server()
        try:
            config = _config(base_url=str(server.make_url("")).rstrip("/"))
            with pytest.raises(OpenCodeGoUnavailableError):
                await OpenCodeGoClient(config).fetch_usage()
        finally:
            await server.close()
