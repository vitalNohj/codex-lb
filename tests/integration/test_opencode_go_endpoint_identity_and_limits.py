"""Endpoint identity, response size, and cancellation on the real quota path.

Three defects found in full-fleet PR review and routed to their owners. Each is
reproduced here against the composed code with bounded synthetic inputs - no
real provider traffic, no credential, nothing unbounded actually allocated.

1. **Go/Zen predicate accepts a fragment or query.** `is_opencode_go_base_url`
   matches `/go/` anywhere in the raw URL, so `https://opencode.ai/zen/v1#/go/`
   passes. A Go key sent to the Zen path bills pay-as-you-go credits, which is
   the one validation error on this feature that costs real money.
2. **Unbounded `response.text()`.** `_read_response_json` reads the whole body
   with no cap, so a hostile or broken upstream can drive allocation from a
   dashboard request.
3. **Single-flight cancellation.** Concurrent quota readers share one upstream
   request; cancelling the first caller must not abort the waiters.

Tests for defects that are still open assert the **accepted** behavior and carry
`xfail(strict=True)`, so they fail now for the right reason and become hard
failures the moment a fix lands. Nothing is skipped and no assertion is softened.

Owners: codexlb-opencode-go-integration (1) and codexlb-opencode-go-quota-r1
(2, 3). This file is evidence, not a duplicate fix.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.clients.opencode_go_sidecar import is_opencode_go_base_url

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# 1. Go vs Zen endpoint identity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://opencode.ai/zen/go/v1",
        "https://opencode.ai/zen/go/v1/",  # the one tolerated trailing slash
    ],
)
def test_the_canonical_go_base_url_is_accepted(url):
    assert is_opencode_go_base_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://opencode.ai/ZEN/GO/V1",
        "https://opencode.ai/zen//go/v1",
        "https://opencode.ai/zen/./go/v1",
        "https://opencode.ai/zen/go/v1/../go/v1",
    ],
)
def test_a_non_canonical_spelling_of_the_go_url_is_rejected(url):
    """Backend ``c11b9f2e`` accepts only the documented endpoint, spelled exactly.

    An earlier revision of this test asserted that ``/ZEN/GO/V1`` was *accepted*,
    on the assumption that case-folding was harmless. The shipped fix is
    stricter and better: case-folding and empty-segment removal make these
    compare equal to the canonical path while being transmitted verbatim as a
    different path, and callers build request URLs by concatenation. Accepting
    one spelling removes that whole class of disagreement rather than
    enumerating it. My assumption was the weaker one and is corrected here.
    """
    assert is_opencode_go_base_url(url) is False


@pytest.mark.parametrize(
    "url",
    [
        "https://opencode.ai/zen/v1",
        "https://opencode.ai/v1",
        "https://opencode.ai/zen/v1/gold",
        "https://evil.invalid/zen/go/v1",
        "http://opencode.ai/zen/go/v1",
        "",
        "not-a-url",
    ],
)
def test_a_non_go_base_url_is_rejected(url):
    assert is_opencode_go_base_url(url) is False


@pytest.mark.parametrize(
    "url",
    [
        "https://opencode.ai/zen/v1#/go/",
        "https://opencode.ai/zen/v1?x=/go/",
        "https://opencode.ai/zen/v1#anchor/go/more",
        "https://opencode.ai/zen/v1?redirect=https://opencode.ai/zen/go/v1",
    ],
)
def test_a_zen_url_with_go_only_in_the_fragment_or_query_is_rejected(url):
    """Accepted behavior: only the URL *path* may establish Go identity.

    A fragment is never sent to the server at all, and a query string does not
    change which product serves the request - so neither can make a Zen base URL
    into a Go one.
    """
    assert is_opencode_go_base_url(url) is False


def test_go_identity_never_depends_on_a_component_the_server_does_not_receive():
    """States the rule as a property rather than a list of hostile spellings.

    A fragment is never transmitted, and a query string does not change which
    product serves the request, so neither may flip Go identity. Asserted by
    comparing a clean Zen URL against the same URL with ``/go/`` added in each
    component: the verdict must not move.

    Fixed by backend ``c11b9f2e`` (canonical-only Go URL). The expected-failure
    scaffolding this carried while the defect was open has been removed.
    """
    baseline = is_opencode_go_base_url("https://opencode.ai/zen/v1")
    assert baseline is False

    for noisy in (
        "https://opencode.ai/zen/v1#/go/",
        "https://opencode.ai/zen/v1?x=/go/",
        "https://opencode.ai/zen/v1#anchor/go/more",
    ):
        assert is_opencode_go_base_url(noisy) == baseline, (
            f"{noisy!r} changed the Go verdict via a component the server never "
            "receives or that does not select the product"
        )


# ---------------------------------------------------------------------------
# 2. Response size bound
# ---------------------------------------------------------------------------


class _FakeResponse:
    """An upstream that reports a very large body without allocating one.

    ``content_length`` is what a size guard should consult first; ``text()``
    raises if called, so a test can prove the guard refused *before* reading
    rather than after.
    """

    def __init__(self, *, content_length: int) -> None:
        self.status = 200
        self.content_length = content_length
        self.headers = {"Content-Length": str(content_length)}
        self.text_was_called = False

    async def text(self) -> str:
        self.text_was_called = True
        raise AssertionError("the client read an oversized body instead of refusing it on its declared length")


@pytest.mark.asyncio
async def test_an_oversized_usage_body_is_refused_rather_than_read():
    """Accepted behavior: refuse on the declared length, before allocating.

    Synthetic and bounded on purpose - nothing here allocates a large body. The
    fake reports a large ``content_length`` and fails the test if ``text()`` is
    reached at all.
    """
    from app.core.clients.opencode_go import OpenCodeGoUnavailableError, _read_response_json

    response = _FakeResponse(content_length=512 * 1024 * 1024)

    with pytest.raises(OpenCodeGoUnavailableError):
        await _read_response_json(response)  # type: ignore[arg-type]

    assert response.text_was_called is False


@pytest.mark.asyncio
async def test_an_ordinary_usage_body_is_still_read():
    """The bound must not break the normal case."""
    from app.core.clients.opencode_go import _read_response_json

    body = b'{"usage": {"rolling": {"status": "ok", "percent": 1}}}'

    class _Content:
        """Streams the body, matching how the hardened reader consumes it."""

        async def iter_chunked(self, _size: int):
            yield body

    class _Ordinary:
        status = 200
        content_length = len(body)
        headers = {"Content-Length": str(len(body))}
        content = _Content()

        async def text(self) -> str:
            return body.decode()

    parsed = await _read_response_json(_Ordinary())  # type: ignore[arg-type]
    assert parsed["usage"]["rolling"]["percent"] == 1


@pytest.mark.asyncio
async def test_a_body_larger_than_its_declared_length_is_refused_while_streaming():
    """Declared-size refusal is not enough; the wire can disagree with the header.

    A header check only rejects an upstream that is honest about its size. The
    real bound has to hold while the body is consumed, because a hostile or
    broken server can under-declare ``Content-Length``, omit it entirely under
    chunked encoding, or expand under content-encoding.

    Bounded on purpose: this serves ~2 MiB from loopback, enough to exceed any
    sane usage-payload cap while allocating almost nothing. It does not attempt
    to prove a decompression bound - that needs the owner's chosen cap to exist
    first - and is written to fail for the single reason that no streamed limit
    is applied.
    """
    import aiohttp
    from aiohttp import web

    from app.core.clients.opencode_go import OpenCodeGoUnavailableError, _read_response_json

    chunk = b"x" * 64 * 1024
    chunks = 32  # ~2 MiB total, streamed, never held whole in the test

    async def handler(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(status=200, headers={"Content-Type": "application/json"})
        await response.prepare(request)  # chunked: no Content-Length at all
        for _ in range(chunks):
            await response.write(chunk)
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_get("/v1/usage", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = int(runner.addresses[0][1])

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/v1/usage") as response:
                assert response.content_length is None, "expected a chunked body with no declared size"
                with pytest.raises(OpenCodeGoUnavailableError):
                    await _read_response_json(response)
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# 3. Single-flight cancellation
# ---------------------------------------------------------------------------


def _quota_config(api_key: str = "sk-go-single-flight-Zq7SvT2pLm9K"):
    from app.modules.opencode_go.service import OpenCodeGoConfig

    return OpenCodeGoConfig(
        enabled=True,
        base_url="https://opencode.ai/zen/go/v1",
        api_key=api_key,
    )


@pytest.mark.asyncio
async def test_cancelling_the_initiating_quota_caller_still_answers_the_survivor():
    """The reported defect, driven through the real cache rather than a helper.

    An earlier version of this test awaited ``wait_on_shared_future`` directly.
    That was not a reproduction: the previous code already used that helper for
    secondary callers, so the test passed on the defective build and proved
    nothing. Firstmate was right to reject it.

    What actually matters is ``OpenCodeGoQuotaCache.fetch_single_flight``: the
    **initiator** owns the upstream request, and if its task is cancelled the
    request must not be torn down under the callers still waiting on it. Two
    dashboard tabs share one round trip; one navigating away must not break the
    other.
    """
    from app.modules.opencode_go.service import OpenCodeGoQuotaCache

    cache = OpenCodeGoQuotaCache()
    config = _quota_config()
    release = asyncio.get_running_loop().create_future()
    fetch_calls = 0

    async def fetch():
        nonlocal fetch_calls
        fetch_calls += 1
        return await release

    initiator = asyncio.ensure_future(cache.fetch_single_flight(config, fetch))
    await asyncio.sleep(0)
    survivor = asyncio.ensure_future(cache.fetch_single_flight(config, fetch))
    await asyncio.sleep(0)

    # Exactly one upstream request for two callers - the point of single flight.
    assert fetch_calls == 1

    initiator.cancel()
    with pytest.raises(asyncio.CancelledError):
        await initiator
    await asyncio.sleep(0)

    sentinel = object()
    if release.done():
        # The initiator's cancellation propagated into the shared fetch itself,
        # which is precisely the reported defect: the survivor can no longer be
        # answered because the request it joined was torn down.
        pytest.fail(
            "cancelling the initiating caller completed/aborted the shared "
            f"fetch ({release}); the surviving caller cannot be answered"
        )
    release.set_result(sentinel)
    assert await asyncio.wait_for(survivor, timeout=5) is sentinel, (
        "cancelling the initiating caller aborted the shared request and left the surviving caller without an answer"
    )


@pytest.mark.asyncio
async def test_one_upstream_request_serves_every_concurrent_quota_caller():
    from app.modules.opencode_go.service import OpenCodeGoQuotaCache

    cache = OpenCodeGoQuotaCache()
    config = _quota_config()
    release = asyncio.get_running_loop().create_future()
    fetch_calls = 0

    async def fetch():
        nonlocal fetch_calls
        fetch_calls += 1
        return await release

    callers = []
    for _ in range(4):
        callers.append(asyncio.ensure_future(cache.fetch_single_flight(config, fetch)))
        await asyncio.sleep(0)

    sentinel = object()
    release.set_result(sentinel)
    assert await asyncio.wait_for(asyncio.gather(*callers), timeout=5) == [sentinel] * 4
    assert fetch_calls == 1


@pytest.mark.asyncio
async def test_an_upstream_failure_reaches_every_concurrent_quota_caller():
    """One failure must not leave a joined caller hanging forever."""
    from app.modules.opencode_go.service import OpenCodeGoQuotaCache

    cache = OpenCodeGoQuotaCache()
    config = _quota_config()
    release = asyncio.get_running_loop().create_future()

    async def fetch():
        return await release

    callers = []
    for _ in range(3):
        callers.append(asyncio.ensure_future(cache.fetch_single_flight(config, fetch)))
        await asyncio.sleep(0)

    release.set_exception(RuntimeError("upstream down"))
    for caller in callers:
        with pytest.raises(RuntimeError, match="upstream down"):
            await asyncio.wait_for(caller, timeout=5)


@pytest.mark.asyncio
async def test_a_re_keyed_subscription_does_not_receive_the_previous_keys_answer():
    """A config change must start its own request, not join the in-flight one.

    Otherwise rotating the API key could show the previous subscription's
    numbers, which is a cross-credential data leak on a dashboard.
    """
    from app.modules.opencode_go.service import OpenCodeGoQuotaCache

    cache = OpenCodeGoQuotaCache()
    first_release = asyncio.get_running_loop().create_future()
    second_release = asyncio.get_running_loop().create_future()

    async def first_fetch():
        return await first_release

    async def second_fetch():
        return await second_release

    first = asyncio.ensure_future(cache.fetch_single_flight(_quota_config("sk-go-key-one"), first_fetch))
    await asyncio.sleep(0)
    second = asyncio.ensure_future(cache.fetch_single_flight(_quota_config("sk-go-key-two"), second_fetch))
    await asyncio.sleep(0)

    first_answer = object()
    second_answer = object()
    second_release.set_result(second_answer)
    first_release.set_result(first_answer)

    assert await asyncio.wait_for(second, timeout=5) is second_answer, (
        "a re-keyed config joined the previous key's in-flight request"
    )
    assert await asyncio.wait_for(first, timeout=5) is first_answer
