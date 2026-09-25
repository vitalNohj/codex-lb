from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import pytest

from app.modules.proxy.sidecar_upstream_errors import (
    SIDECAR_UPSTREAM_AUTH_RETRY_AFTER_SECONDS,
    SIDECAR_UPSTREAM_UNAVAILABLE_CODE,
    SIDECAR_UPSTREAM_UNAVAILABLE_MESSAGE,
    client_facing_sidecar_error,
    is_sidecar_upstream_auth_failure,
    open_sidecar_stream,
    relay_sidecar_stream,
)


def test_is_sidecar_upstream_auth_failure_only_401_403() -> None:
    assert is_sidecar_upstream_auth_failure(401)
    assert is_sidecar_upstream_auth_failure(403)
    assert not is_sidecar_upstream_auth_failure(400)
    assert not is_sidecar_upstream_auth_failure(429)
    assert not is_sidecar_upstream_auth_failure(500)
    assert not is_sidecar_upstream_auth_failure(503)


def test_client_facing_sidecar_error_remaps_missing_api_key_401() -> None:
    result = client_facing_sidecar_error(
        status_code=401,
        message="[401]: Missing API key",
        error_code="omniroute_sidecar_error",
        extra_headers={"x-ratelimit-remaining": "9"},
    )

    assert result.status_code == 503
    assert result.headers["Retry-After"] == str(SIDECAR_UPSTREAM_AUTH_RETRY_AFTER_SECONDS)
    assert result.headers["x-ratelimit-remaining"] == "9"
    assert result.content["error"]["code"] == SIDECAR_UPSTREAM_UNAVAILABLE_CODE
    assert result.content["error"]["message"] == SIDECAR_UPSTREAM_UNAVAILABLE_MESSAGE
    assert "Missing API key" not in result.content["error"]["message"]
    assert "[401]" not in result.content["error"]["message"]


def test_client_facing_sidecar_error_remaps_403() -> None:
    result = client_facing_sidecar_error(
        status_code=403,
        message="forbidden",
        error_code="openrouter_sidecar_error",
    )

    assert result.status_code == 503
    assert result.headers["Retry-After"] == str(SIDECAR_UPSTREAM_AUTH_RETRY_AFTER_SECONDS)
    assert result.content["error"]["code"] == SIDECAR_UPSTREAM_UNAVAILABLE_CODE


def test_client_facing_sidecar_error_passthrough_non_auth() -> None:
    body = {"error": {"message": "model overloaded", "type": "server_error", "code": "overloaded"}}
    result = client_facing_sidecar_error(
        status_code=529,
        message="model overloaded",
        error_code="omniroute_sidecar_error",
        body=body,
        extra_headers={"x-request-id": "abc"},
    )

    assert result.status_code == 529
    assert "Retry-After" not in result.headers
    assert result.headers["x-request-id"] == "abc"
    assert result.content == body


def test_client_facing_sidecar_error_wraps_when_body_not_envelope() -> None:
    result = client_facing_sidecar_error(
        status_code=502,
        message="bad gateway",
        error_code="claude_sidecar_error",
        body="not-json",
    )

    assert result.status_code == 502
    assert result.content["error"]["code"] == "claude_sidecar_error"
    assert result.content["error"]["message"] == "bad gateway"


class _ProviderError(Exception):
    def __init__(self, status_code: int, *, retryable: bool = True) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code
        self.retryable = retryable


_Attempt = BaseException | list[bytes | BaseException]


class _Upstream:
    """A scripted upstream: each open takes the next attempt.

    An exception attempt fails the open; a list is the response body, where an
    exception fails the stream at that point. Every opened response counts a
    close when it is released.
    """

    def __init__(self, *attempts: _Attempt) -> None:
        self._attempts = list(attempts)
        self.opens = 0
        self.closes = 0

    def open(self) -> AbstractAsyncContextManager[AsyncIterator[bytes]]:
        self.opens += 1
        return self._response(self._attempts.pop(0))

    @asynccontextmanager
    async def _response(self, attempt: _Attempt) -> AsyncIterator[AsyncIterator[bytes]]:
        if isinstance(attempt, BaseException):
            raise attempt
        try:
            yield _body(attempt)
        finally:
            self.closes += 1


async def _body(chunks: list[bytes | BaseException]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        if isinstance(chunk, BaseException):
            raise chunk
        yield chunk


async def _relay_all(upstream: _Upstream, relayed: list[bytes] | None = None) -> list[bytes]:
    relayed = [] if relayed is None else relayed
    opened = await open_sidecar_stream(upstream.open, provider="Test", model="m")
    async for chunk in relay_sidecar_stream(opened, upstream.open, provider="Test", model="m"):
        relayed.append(chunk)
    return relayed


@pytest.mark.asyncio
async def test_open_sidecar_stream_retries_a_provider_failure_once() -> None:
    upstream = _Upstream(_ProviderError(502), [b"a", b"b"])

    assert await _relay_all(upstream) == [b"a", b"b"]
    assert upstream.opens == 2
    assert upstream.closes == 1


@pytest.mark.asyncio
async def test_open_sidecar_stream_raises_the_second_failure() -> None:
    second = _ProviderError(503)
    upstream = _Upstream(_ProviderError(502), second)

    with pytest.raises(_ProviderError) as raised:
        await open_sidecar_stream(upstream.open, provider="Test", model="m")

    assert raised.value is second
    assert upstream.opens == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [_ProviderError(429), _ProviderError(503, retryable=False), RuntimeError("no status")],
    ids=["4xx", "not-retryable", "no-status"],
)
async def test_open_sidecar_stream_does_not_retry_other_failures(failure: Exception) -> None:
    upstream = _Upstream(failure)

    with pytest.raises(type(failure)):
        await open_sidecar_stream(upstream.open, provider="Test", model="m")

    assert upstream.opens == 1


@pytest.mark.asyncio
async def test_relay_reopens_once_when_the_stream_fails_before_its_first_chunk() -> None:
    upstream = _Upstream([_ProviderError(503)], [b"a"])

    assert await _relay_all(upstream) == [b"a"]
    assert upstream.opens == 2
    assert upstream.closes == 2


@pytest.mark.asyncio
async def test_relay_does_not_reopen_when_the_open_spent_the_retry() -> None:
    failure = _ProviderError(503)
    upstream = _Upstream(_ProviderError(502), [failure], [b"never"])

    with pytest.raises(_ProviderError) as raised:
        await _relay_all(upstream)

    assert raised.value is failure
    assert upstream.opens == 2
    assert upstream.closes == 1


@pytest.mark.asyncio
async def test_relay_does_not_reopen_after_the_first_chunk() -> None:
    failure = _ProviderError(503)
    upstream = _Upstream([b"a", failure], [b"never"])
    relayed: list[bytes] = []

    with pytest.raises(_ProviderError) as raised:
        await _relay_all(upstream, relayed)

    assert raised.value is failure
    assert relayed == [b"a"]
    assert upstream.opens == 1
    assert upstream.closes == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [_ProviderError(400), _ProviderError(503, retryable=False), asyncio.CancelledError()],
    ids=["4xx", "not-retryable", "cancelled"],
)
async def test_relay_does_not_reopen_other_failures(failure: BaseException) -> None:
    upstream = _Upstream([failure], [b"never"])

    with pytest.raises(type(failure)):
        await _relay_all(upstream)

    assert upstream.opens == 1
    assert upstream.closes == 1


@pytest.mark.asyncio
async def test_closing_the_relay_closes_the_upstream() -> None:
    upstream = _Upstream([b"a", b"b"])
    opened = await open_sidecar_stream(upstream.open, provider="Test", model="m")
    relay = relay_sidecar_stream(opened, upstream.open, provider="Test", model="m")

    assert await anext(relay) == b"a"
    await relay.aclose()

    assert upstream.opens == 1
    assert upstream.closes == 1
