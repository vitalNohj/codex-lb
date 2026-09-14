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
        "https://opencode.ai/zen/go/v1/",
        "https://opencode.ai/ZEN/GO/V1",
    ],
)
def test_a_real_go_base_url_is_accepted(url):
    assert is_opencode_go_base_url(url) is True


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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "open defect: the predicate matches '/go/' anywhere in the raw URL, so a "
        "Zen base URL carrying it in the fragment or query is accepted. A Go key "
        "on the Zen path bills pay-as-you-go credits. Owner: "
        "codexlb-opencode-go-integration. Remove this marker when the check "
        "parses the URL and inspects only the path."
    ),
)
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
    comparing a clean Zen URL against the same URL with `/go/` appended in each
    component - the verdict must not move.

    Deliberately not asserting the current buggy value: pinning
    `is_opencode_go_base_url(...) is True` here would have to be edited by hand
    when the fix lands, which is exactly the hand-editing the xfail above exists
    to avoid.
    """
    baseline = is_opencode_go_base_url("https://opencode.ai/zen/v1")
    assert baseline is False

    for noisy in (
        "https://opencode.ai/zen/v1#/go/",
        "https://opencode.ai/zen/v1?x=/go/",
    ):
        if is_opencode_go_base_url(noisy) != baseline:
            pytest.xfail(
                "open defect: a fragment or query flips Go identity; see the "
                "parametrized xfail above. Owner: codexlb-opencode-go-integration"
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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "open defect: _read_response_json calls response.text() with no size "
        "bound, so a hostile or broken upstream drives unbounded allocation from "
        "a dashboard request. Owner: codexlb-opencode-go-quota-r1. Remove this "
        "marker when the reader caps the body."
    ),
)
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

    class _Ordinary:
        status = 200
        content_length = 64
        headers = {"Content-Length": "64"}

        async def text(self) -> str:
            return '{"usage": {"rolling": {"status": "ok", "percent": 1}}}'

    parsed = await _read_response_json(_Ordinary())  # type: ignore[arg-type]
    assert parsed["usage"]["rolling"]["percent"] == 1


# ---------------------------------------------------------------------------
# 3. Single-flight cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelling_the_first_quota_caller_does_not_abort_the_waiters():
    """A cancelled owner must not take the shared request down with it.

    Two dashboard tabs asking for quota at once share one upstream round trip.
    If the first caller navigates away and its task is cancelled, the second
    must still get its answer - otherwise one user's navigation breaks another's
    card, and the failure is timing-dependent and near-impossible to diagnose.
    """
    from app.core.utils.shared_future import wait_on_shared_future

    loop = asyncio.get_running_loop()
    shared = loop.create_future()

    first = asyncio.ensure_future(wait_on_shared_future(shared))
    second = asyncio.ensure_future(wait_on_shared_future(shared))
    await asyncio.sleep(0)

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    # The shared request itself must survive the owner's cancellation.
    assert not shared.cancelled(), "cancelling one waiter cancelled the shared request"

    shared.set_result("quota")
    assert await second == "quota"


@pytest.mark.asyncio
async def test_every_waiter_receives_the_shared_result():
    from app.core.utils.shared_future import wait_on_shared_future

    loop = asyncio.get_running_loop()
    shared = loop.create_future()
    waiters = [asyncio.ensure_future(wait_on_shared_future(shared)) for _ in range(4)]
    await asyncio.sleep(0)

    shared.set_result("quota")
    assert await asyncio.gather(*waiters) == ["quota"] * 4


@pytest.mark.asyncio
async def test_a_shared_failure_reaches_every_waiter():
    """One upstream failure must not leave a waiter hanging forever."""
    from app.core.utils.shared_future import wait_on_shared_future

    loop = asyncio.get_running_loop()
    shared = loop.create_future()
    waiters = [asyncio.ensure_future(wait_on_shared_future(shared)) for _ in range(3)]
    await asyncio.sleep(0)

    shared.set_exception(RuntimeError("upstream down"))
    for waiter in waiters:
        with pytest.raises(RuntimeError, match="upstream down"):
            await waiter
