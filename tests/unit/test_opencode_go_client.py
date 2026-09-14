"""Transport tests for the OpenCode Go usage client.

Every HTTP interaction is a local fake injected over ``lease_http_session``. No
real credentials, no network, no production data: the "keys" here are invented
strings whose only purpose is to prove they never survive into a message.
"""

from __future__ import annotations

import asyncio
import contextlib

import aiohttp
import pytest

from app import __version__
from app.core.clients.opencode_go import (
    DEFAULT_OPENCODE_GO_BASE_URL,
    NON_JSON_BODY_KEY,
    OPENCODE_GO_USER_AGENT,
    OpenCodeGoClient,
    OpenCodeGoConfig,
    OpenCodeGoError,
    OpenCodeGoUnavailableError,
    sanitize_opencode_go_message,
)
from app.core.usage.opencode_go_quota import (
    OpenCodeGoQuotaParseError,
    parse_opencode_go_usage,
)

pytestmark = pytest.mark.unit

_FAKE_KEY = "sk-oc-go-t3st-000000000000"


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


class _FakeResponse:
    def __init__(self, status: int, text: str | Exception) -> None:
        self.status = status
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def text(self) -> str:
        if isinstance(self._text, Exception):
            raise self._text
        return self._text


class _FakeSession:
    def __init__(self, response: _FakeResponse | Exception) -> None:
        self._response = response
        self.url: str | None = None
        self.headers: dict[str, str] | None = None
        self.timeout: aiohttp.ClientTimeout | None = None
        self.calls = 0

    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        self.url = url
        self.headers = dict(headers or {})
        self.timeout = timeout
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


@contextlib.asynccontextmanager
async def _lease(session: _FakeSession):
    yield session


@pytest.fixture
def patch_session(monkeypatch):
    def _apply(response: _FakeResponse | Exception) -> _FakeSession:
        session = _FakeSession(response)
        monkeypatch.setattr(
            "app.core.clients.opencode_go.lease_http_session",
            lambda: _lease(session),
        )
        return session

    return _apply


@pytest.mark.asyncio
async def test_fetch_usage_returns_parsed_body(patch_session):
    session = patch_session(_FakeResponse(200, '{"usage": {"rolling": {"status": "ok", "percent": 5}}}'))

    body = await OpenCodeGoClient(_config()).fetch_usage()

    assert body == {"usage": {"rolling": {"status": "ok", "percent": 5}}}
    assert session.url == "https://opencode.ai/zen/go/v1/usage"


@pytest.mark.asyncio
async def test_request_sends_honest_client_identity_and_no_fake_session(patch_session):
    session = patch_session(_FakeResponse(200, '{"usage": {}}'))

    await OpenCodeGoClient(_config()).fetch_usage()

    # The Go docs require a client-specific user agent. The reviewed Python
    # prior art spoofs Chrome to dodge a bot challenge; that is deliberately
    # not reused.
    assert session.headers["User-Agent"] == OPENCODE_GO_USER_AGENT
    assert __version__ in session.headers["User-Agent"]
    assert "Mozilla" not in session.headers["User-Agent"]
    assert session.headers["Authorization"] == f"Bearer {_FAKE_KEY}"
    # No evidence establishes that /usage requires or interprets a session id,
    # so none is synthesized.
    assert "x-opencode-session" not in {name.lower() for name in session.headers}


@pytest.mark.asyncio
async def test_request_timeouts_are_bounded(patch_session):
    session = patch_session(_FakeResponse(200, "{}"))

    await OpenCodeGoClient(_config(connect_timeout_seconds=2.0, request_timeout_seconds=7.0)).fetch_usage()

    assert session.timeout.total == 7.0
    assert session.timeout.connect == 2.0
    assert session.timeout.sock_connect == 2.0


@pytest.mark.asyncio
async def test_base_url_trailing_slash_is_normalized(patch_session):
    session = patch_session(_FakeResponse(200, "{}"))

    await OpenCodeGoClient(_config(base_url="https://opencode.ai/zen/go/v1/")).fetch_usage()

    assert session.url == "https://opencode.ai/zen/go/v1/usage"


@pytest.mark.asyncio
async def test_missing_key_never_issues_an_unauthenticated_probe(patch_session):
    session = patch_session(_FakeResponse(200, "{}"))

    with pytest.raises(OpenCodeGoError) as excinfo:
        await OpenCodeGoClient(_config(api_key=None)).fetch_usage()

    assert excinfo.value.status_code == 401
    assert session.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
async def test_http_error_statuses_are_surfaced_with_their_code(patch_session, status):
    patch_session(_FakeResponse(status, '{"error": {"message": "upstream said no"}}'))

    with pytest.raises(OpenCodeGoError) as excinfo:
        await OpenCodeGoClient(_config()).fetch_usage()

    assert excinfo.value.status_code == status
    assert excinfo.value.message == "upstream said no"


@pytest.mark.asyncio
async def test_real_upstream_auth_error_body_shape(patch_session):
    """The exact 401 body the live endpoint returns without a key."""
    patch_session(
        _FakeResponse(401, '{"type":"error","error":{"type":"AuthError","message":"Missing API key."}}'),
    )

    with pytest.raises(OpenCodeGoError) as excinfo:
        await OpenCodeGoClient(_config()).fetch_usage()

    assert excinfo.value.status_code == 401
    assert excinfo.value.message == "Missing API key."


@pytest.mark.asyncio
async def test_flat_message_error_body(patch_session):
    patch_session(_FakeResponse(500, '{"message": "internal"}'))

    with pytest.raises(OpenCodeGoError) as excinfo:
        await OpenCodeGoClient(_config()).fetch_usage()

    assert excinfo.value.message == "internal"


@pytest.mark.asyncio
async def test_non_json_error_body_falls_back_to_the_status(patch_session):
    patch_session(_FakeResponse(502, "<html>bad gateway</html>"))

    with pytest.raises(OpenCodeGoError) as excinfo:
        await OpenCodeGoClient(_config()).fetch_usage()

    assert excinfo.value.status_code == 502
    assert "502" in excinfo.value.message
    assert "bad gateway" in excinfo.value.message


@pytest.mark.asyncio
async def test_long_non_json_error_body_is_truncated(patch_session):
    """An upstream error page must not become a page-long dashboard message."""
    patch_session(_FakeResponse(500, "<html>" + ("x" * 50_000) + "</html>"))

    with pytest.raises(OpenCodeGoError) as excinfo:
        await OpenCodeGoClient(_config()).fetch_usage()

    assert len(excinfo.value.message) < 250


@pytest.mark.asyncio
async def test_html_success_body_is_not_mistaken_for_usage(patch_session):
    """A 200 that is not JSON must not read as a usage document.

    It is parked under a private key rather than ``message`` so it can neither
    parse as usage nor be promoted into an operator-visible error string.
    """
    patch_session(_FakeResponse(200, "<!DOCTYPE html><html>404</html>"))

    body = await OpenCodeGoClient(_config()).fetch_usage()

    assert body == {NON_JSON_BODY_KEY: "<!DOCTYPE html><html>404</html>"}
    assert "message" not in body
    with pytest.raises(OpenCodeGoQuotaParseError):
        parse_opencode_go_usage(body)


@pytest.mark.asyncio
async def test_empty_body_is_an_empty_object(patch_session):
    patch_session(_FakeResponse(200, ""))

    assert await OpenCodeGoClient(_config()).fetch_usage() == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        asyncio.TimeoutError(),
        aiohttp.ClientConnectionError("connection refused"),
        aiohttp.ServerDisconnectedError(),
        OSError("network unreachable"),
    ],
)
async def test_transport_failures_become_unavailable(patch_session, exc):
    patch_session(exc)

    with pytest.raises(OpenCodeGoUnavailableError) as excinfo:
        await OpenCodeGoClient(_config()).fetch_usage()

    assert excinfo.value.status_code == 503


@pytest.mark.asyncio
async def test_disconnect_while_reading_the_body_becomes_unavailable(patch_session):
    patch_session(_FakeResponse(200, aiohttp.ServerDisconnectedError()))

    with pytest.raises(OpenCodeGoUnavailableError):
        await OpenCodeGoClient(_config()).fetch_usage()


@pytest.mark.asyncio
async def test_upstream_that_echoes_the_credential_does_not_leak_it(patch_session):
    patch_session(_FakeResponse(401, f'{{"error": {{"message": "rejected Authorization: Bearer {_FAKE_KEY}"}}}}'))

    with pytest.raises(OpenCodeGoError) as excinfo:
        await OpenCodeGoClient(_config()).fetch_usage()

    assert _FAKE_KEY not in excinfo.value.message
    assert "[redacted]" in excinfo.value.message


@pytest.mark.asyncio
async def test_transport_error_text_cannot_leak_the_credential(patch_session):
    patch_session(aiohttp.ClientConnectionError(f"proxy rejected key {_FAKE_KEY}"))

    with pytest.raises(OpenCodeGoUnavailableError) as excinfo:
        await OpenCodeGoClient(_config()).fetch_usage()

    assert _FAKE_KEY not in excinfo.value.message


class TestSanitizer:
    def test_redacts_the_configured_key_bare(self):
        assert _FAKE_KEY not in sanitize_opencode_go_message(f"bad key {_FAKE_KEY}", api_key=_FAKE_KEY)

    def test_redacts_a_bearer_token_that_is_not_the_configured_key(self):
        message = sanitize_opencode_go_message("Bearer sk-oc-go-someoneelse-999", api_key=None)

        assert "someoneelse" not in message
        assert "[redacted]" in message

    def test_short_alphabetic_value_does_not_corrupt_prose(self):
        """A short all-letter key is ambiguous with a word upstream may echo."""
        message = sanitize_opencode_go_message("Invalid API key", api_key="key")

        assert message == "Invalid API key"

    def test_short_alphabetic_value_is_still_redacted_in_credential_position(self):
        message = sanitize_opencode_go_message("Authorization: key", api_key="key")

        assert message == "Authorization: [redacted]"

    def test_long_alphabetic_key_is_redacted_anywhere(self):
        opaque = "abcdefghijklmnopqrstuvwxyz"

        assert opaque not in sanitize_opencode_go_message(f"rejected {opaque}", api_key=opaque)

    def test_key_embedded_in_a_longer_word_is_not_a_match(self):
        message = sanitize_opencode_go_message("monkeyspanner", api_key="key")

        assert message == "monkeyspanner"

    def test_no_key_configured_leaves_ordinary_text_intact(self):
        assert sanitize_opencode_go_message("Missing API key.", api_key=None) == "Missing API key."
