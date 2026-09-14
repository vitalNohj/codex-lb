from __future__ import annotations

import asyncio

import aiohttp
import pytest

from app import __version__
from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.opencode_go_sidecar import (
    OpenCodeGoSidecarClient,
    OpenCodeGoSidecarConfig,
    OpenCodeGoSidecarError,
    OpenCodeGoSidecarUnavailableError,
    get_opencode_go_sidecar_client,
    is_opencode_go_base_url,
    opencode_go_request_headers,
    reset_opencode_go_sidecar_client_cache,
    sanitize_opencode_go_error_body,
    sanitize_opencode_go_message,
)

pytestmark = pytest.mark.unit


def _config(**overrides) -> OpenCodeGoSidecarConfig:
    values = {
        "enabled": True,
        "base_url": "https://opencode.ai/zen/go/v1",
        "api_key": None,
        "prefixes": (SidecarPrefix(prefix="opencode-go/", strip=True),),
        "connect_timeout_seconds": 8.0,
        "request_timeout_seconds": 600.0,
        "models_cache_ttl_seconds": 60.0,
    }
    values.update(overrides)
    return OpenCodeGoSidecarConfig(**values)


class _FakeContent:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _size: int):
        for chunk in self._chunks:
            yield chunk


class _FakeResponse:
    def __init__(
        self,
        status: int,
        text: str,
        chunks: list[bytes] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self._text = text
        # The client reads bodies by streaming ``content`` under a byte cap, so
        # a fake that only served ``text()`` would exercise a path the real
        # client no longer takes. When a test supplies ``text`` and no explicit
        # chunks, serve those same bytes through ``content``.
        if chunks is None and text:
            chunks = [text.encode("utf-8")]
        self.content = _FakeContent(chunks or [])
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def text(self) -> str:
        return self._text


class _FakeSession:
    def __init__(
        self,
        *,
        get_response: _FakeResponse | Exception | None = None,
        post_response: _FakeResponse | Exception | None = None,
    ) -> None:
        self.get_response = get_response
        self.post_response = post_response
        self.last_url: str | None = None
        self.last_headers: dict[str, str] | None = None
        self.last_json = None

    def get(self, url: str, *, headers, timeout):
        self.last_url = url
        self.last_headers = headers
        if isinstance(self.get_response, Exception):
            raise self.get_response
        assert self.get_response is not None
        return self.get_response

    def post(self, url: str, *, headers, json, timeout):
        self.last_url = url
        self.last_headers = headers
        self.last_json = json
        if isinstance(self.post_response, Exception):
            raise self.post_response
        assert self.post_response is not None
        return self.post_response


class _Lease:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def _patch(monkeypatch, session: _FakeSession) -> None:
    monkeypatch.setattr("app.core.clients.opencode_go_sidecar.lease_http_session", lambda: _Lease(session))


# --------------------------------------------------------------------------
# Go vs Zen
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # The documented endpoint, plus transcription noise that provably cannot
        # change the transmitted path (callers rstrip("/") before concatenating).
        ("https://opencode.ai/zen/go/v1", True),
        ("https://opencode.ai/zen/go/v1/", True),
        ("  https://opencode.ai/zen/go/v1  ", True),
        # Zen is a different product with different billing.
        ("https://opencode.ai/zen/v1", False),
        ("https://opencode.ai/zen/v1/gold", False),
        ("https://opencode.ai/zen/going/v1", False),
        ("https://opencode.ai/zen/go/v1/extra", False),
        # A /go/ path on some other host says nothing about which product bills.
        ("https://example.com/zen/go/v1", False),
        ("https://opencode.ai.evil.com/zen/go/v1", False),
        # The credential is a bearer token; it must not go out in the clear.
        ("http://opencode.ai/zen/go/v1", False),
        ("", False),
        ("../../etc", False),
    ],
)
def test_is_opencode_go_base_url_distinguishes_go_from_zen(url: str, expected: bool) -> None:
    assert is_opencode_go_base_url(url) is expected


class TestOnlyTheDocumentedEndpointIsAccepted:
    """Accepted bases must stay safe under the concatenation callers perform.

    Every caller builds requests as ``f"{base_url}/chat/completions"`` (also
    ``/models`` and ``/usage``), so the question is not whether a string *looks*
    like Go but whether ``<base>/<suffix>`` reaches Go. Successive reviews found
    that gap in progressively subtler places, so the validator now accepts only
    the one documented spelling. Each case below is a shape an earlier version
    accepted while the resulting request went elsewhere.
    """

    @pytest.mark.parametrize(
        "url",
        [
            # Fragment/query: never transmitted as path, so a substring scan for
            # "/go/" passed while the request path stayed /zen/v1.
            "https://opencode.ai/zen/v1#/go/v1",
            "https://opencode.ai/zen/v1?x=/go/v1",
            # Dot segments resolve away before the request is sent.
            "https://opencode.ai/zen/go/../v1",
            "https://opencode.ai/zen/go/v1/../../v1",
        ],
        ids=["fragment", "query", "dotdot", "dotdot-deep"],
    )
    def test_a_url_whose_wire_path_is_zen_is_rejected(self, url: str) -> None:
        assert is_opencode_go_base_url(url) is False

    @pytest.mark.parametrize(
        "url",
        [
            # EMPTY delimiters: structural parsing saw a falsy fragment/query and
            # allowed these, but the appended suffix lands *inside* the fragment
            # or query, so /chat/completions is never requested at all.
            "https://opencode.ai/zen/go/v1#",
            "https://opencode.ai/zen/go/v1?",
            # Empty userinfo - a delimiter with nothing in it.
            "https://@opencode.ai/zen/go/v1",
        ],
        ids=["empty-fragment", "empty-query", "empty-userinfo"],
    )
    def test_empty_component_delimiters_are_rejected(self, url: str) -> None:
        """An empty delimiter is still a delimiter.

        Truthiness checks miss these precisely because the component is empty,
        which is what made them survive a structural rewrite.
        """

        assert is_opencode_go_base_url(url) is False

    @pytest.mark.parametrize(
        "url",
        [
            # Case-folding and empty-segment removal made these compare equal to
            # the canonical path, yet they are transmitted verbatim as different
            # paths.
            "https://opencode.ai/ZEN/GO/v1",
            "https://opencode.ai/zen//go/v1",
            "https://opencode.ai/zen/./go/v1",
            "https://opencode.ai/zen/%67%6f/v1",
            "https://opencode.ai/zen/go%2Fv1",
        ],
        ids=["uppercase", "double-slash", "dot-segment", "percent-encoded", "encoded-separator"],
    )
    def test_noncanonical_path_spellings_are_rejected(self, url: str) -> None:
        """Normalizing these would require proving equivalence to the sent path.

        Some do reach Go and some do not; rather than maintain a second URL
        resolver to tell them apart, only the canonical spelling is accepted.
        """

        assert is_opencode_go_base_url(url) is False

    @pytest.mark.parametrize(
        "url",
        [
            "https://user:pw@opencode.ai/zen/go/v1",
            "https://opencode.ai:8443/zen/go/v1",
        ],
        ids=["userinfo", "port"],
    )
    def test_components_with_no_legitimate_use_here_are_rejected(self, url: str) -> None:
        assert is_opencode_go_base_url(url) is False

    @pytest.mark.parametrize(
        "url",
        [
            "https://opencode.ai/zen/go/v1",
            "https://opencode.ai/zen/go/v1/",
            "https://opencode.ai/zen/go/v1#",
            "https://opencode.ai/zen/go/v1?",
            "https://opencode.ai/ZEN/GO/v1",
            "https://opencode.ai/zen//go/v1",
            "https://opencode.ai/zen/%67%6f/v1",
            "https://opencode.ai/zen/go%2Fv1",
            "https://opencode.ai/zen/./go/v1",
            "https://opencode.ai/zen/v1#/go/v1",
            "https://opencode.ai/zen/v1?x=/go/v1",
            "https://opencode.ai/zen/go/../v1",
            "https://opencode.ai/zen/v1",
        ],
    )
    def test_anything_accepted_actually_reaches_go_when_a_suffix_is_appended(self, url: str) -> None:
        """The safety property itself, derived rather than hand-asserted.

        Builds the URL exactly as the client does and requires that an accepted
        base always produces a Go request path. Rejecting a URL that would have
        worked is merely strict; accepting one that would not is the bug this
        guards. No request is made and no credential is involved.
        """

        from yarl import URL

        if not is_opencode_go_base_url(url):
            return

        wire_path = URL(f"{url.strip().rstrip('/')}/chat/completions").raw_path

        assert wire_path.startswith("/zen/go/v1/"), f"accepted base does not reach Go: {wire_path}"


def test_all_three_validation_seams_reject_a_wire_path_bypass() -> None:
    """Static config, dashboard schema and the client must agree.

    Pinning all three together is the point: one permissive entry point is
    enough to route a Go key to Zen, and the gap here survived two earlier
    fixes that each looked correct in isolation.
    """

    from app.core.config.settings import Settings
    from app.modules.settings.schemas import _normalize_opencode_go_sidecar_base_url

    for bypass in (
        "https://opencode.ai/zen/v1#/go/v1",
        "https://opencode.ai/zen/go/v1#",
        "https://opencode.ai/ZEN/GO/v1",
    ):
        assert is_opencode_go_base_url(bypass) is False
        with pytest.raises(ValueError, match="OpenCode Go endpoint"):
            Settings(opencode_go_sidecar_base_url=bypass)
        with pytest.raises(ValueError, match="OpenCode Go endpoint"):
            _normalize_opencode_go_sidecar_base_url(bypass)

    # The canonical endpoint still passes every seam.
    canonical = "https://opencode.ai/zen/go/v1"
    assert is_opencode_go_base_url(canonical) is True
    assert Settings(opencode_go_sidecar_base_url=canonical).opencode_go_sidecar_base_url == canonical
    assert _normalize_opencode_go_sidecar_base_url(canonical) == canonical


# --------------------------------------------------------------------------
# Headers / user agent
# --------------------------------------------------------------------------


def test_request_headers_carry_codex_lb_user_agent_and_bearer() -> None:
    headers = opencode_go_request_headers(_config(api_key="sk-go-secret"))

    # Go's client obligations ask for a client-specific user agent, not a
    # generic SDK or HTTP-library name.
    assert headers["User-Agent"] == f"codex-lb/{__version__}"
    assert headers["Authorization"] == "Bearer sk-go-secret"
    assert headers["Accept"] == "application/json"


def test_request_headers_omit_authorization_when_unconfigured() -> None:
    headers = opencode_go_request_headers(_config(api_key=None))

    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_models_request_uses_go_path_and_user_agent(monkeypatch) -> None:
    session = _FakeSession(get_response=_FakeResponse(200, '{"object":"list","data":[]}'))
    _patch(monkeypatch, session)

    await OpenCodeGoSidecarClient(_config(api_key="sk-go-key")).list_models()

    assert session.last_url == "https://opencode.ai/zen/go/v1/models"
    assert session.last_headers["User-Agent"] == f"codex-lb/{__version__}"


# --------------------------------------------------------------------------
# Model listing
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_models_parses_listing_and_publishes_no_prices(monkeypatch) -> None:
    from app.core.usage.runtime_pricing import get_runtime_pricing_registry

    get_runtime_pricing_registry().clear()
    session = _FakeSession(
        get_response=_FakeResponse(
            200,
            '{"object":"list","data":['
            '{"id":"glm-5.3","object":"model","created":1789353162,"owned_by":"opencode"},'
            '{"id":"kimi-k3","object":"model","created":1789353162}'
            "]}",
        )
    )
    _patch(monkeypatch, session)

    models = await OpenCodeGoSidecarClient(_config(api_key="sk-go-key")).list_models()

    assert [model.id for model in models] == ["glm-5.3", "kimi-k3"]
    assert models[1].owned_by == "opencode"
    # Go's listing carries no pricing block at all. Writing an empty price would
    # assert "this model is free"; the correct statement is "this endpoint does
    # not say", so nothing is published.
    assert all(model.pricing is None for model in models)
    assert get_runtime_pricing_registry().runtime_pricing_for_model("glm-5.3", provider="opencode_go") is None


@pytest.mark.asyncio
async def test_list_models_rejects_malformed_payload(monkeypatch) -> None:
    _patch(monkeypatch, _FakeSession(get_response=_FakeResponse(200, '{"object":"list"}')))

    with pytest.raises(OpenCodeGoSidecarError) as excinfo:
        await OpenCodeGoSidecarClient(_config()).list_models()

    assert excinfo.value.status_code == 502


@pytest.mark.asyncio
async def test_list_models_cached_serves_stale_after_failure(monkeypatch) -> None:
    good = _FakeSession(get_response=_FakeResponse(200, '{"object":"list","data":[{"id":"glm-5.3"}]}'))
    _patch(monkeypatch, good)
    client = OpenCodeGoSidecarClient(_config(api_key="sk-go-key", models_cache_ttl_seconds=0.0))
    assert [m.id for m in await client.list_models_cached()] == ["glm-5.3"]

    _patch(monkeypatch, _FakeSession(get_response=aiohttp.ClientError("boom")))
    # TTL is zero, so this call refetches, fails, and must fall back to the
    # cached listing rather than reporting an empty catalogue.
    assert [m.id for m in await client.list_models_cached()] == ["glm-5.3"]


# --------------------------------------------------------------------------
# Errors, Retry-After, transport
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_completion_surfaces_upstream_error_message(monkeypatch) -> None:
    _patch(
        monkeypatch,
        _FakeSession(post_response=_FakeResponse(400, '{"error":{"message":"bad model","type":"invalid"}}')),
    )

    with pytest.raises(OpenCodeGoSidecarError) as excinfo:
        await OpenCodeGoSidecarClient(_config(api_key="sk-go-key")).chat_completion({"model": "glm-5.3"})

    assert excinfo.value.status_code == 400
    assert excinfo.value.message == "bad model"


@pytest.mark.asyncio
async def test_retry_after_is_captured_verbatim_from_429(monkeypatch) -> None:
    _patch(
        monkeypatch,
        _FakeSession(
            post_response=_FakeResponse(
                429,
                '{"error":{"message":"rate limited"}}',
                headers={"Retry-After": "137"},
            )
        ),
    )

    with pytest.raises(OpenCodeGoSidecarError) as excinfo:
        await OpenCodeGoSidecarClient(_config(api_key="sk-go-key")).chat_completion({"model": "glm-5.3"})

    assert excinfo.value.status_code == 429
    # Relayed, not recomputed: only the upstream knows when its window reopens,
    # and Go's caps are hard dollar limits where a too-short guess is costly.
    assert excinfo.value.retry_after == "137"


@pytest.mark.asyncio
async def test_transport_failure_becomes_unavailable(monkeypatch) -> None:
    _patch(monkeypatch, _FakeSession(post_response=asyncio.TimeoutError()))

    with pytest.raises(OpenCodeGoSidecarUnavailableError) as excinfo:
        await OpenCodeGoSidecarClient(_config()).chat_completion({"model": "glm-5.3"})

    assert excinfo.value.status_code == 503


# --------------------------------------------------------------------------
# Streaming
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_chat_completion_yields_chunks(monkeypatch) -> None:
    chunks = [b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n', b"data: [DONE]\n\n"]
    _patch(monkeypatch, _FakeSession(post_response=_FakeResponse(200, "", chunks=chunks)))

    received: list[bytes] = []
    async with OpenCodeGoSidecarClient(_config(api_key="sk-go-key")).stream_chat_completion(
        {"model": "glm-5.3", "stream": True}
    ) as stream:
        async for chunk in stream:
            received.append(chunk)

    assert received == chunks


@pytest.mark.asyncio
async def test_stream_raises_before_yielding_on_upstream_error(monkeypatch) -> None:
    _patch(monkeypatch, _FakeSession(post_response=_FakeResponse(401, '{"error":{"message":"Missing API key."}}')))

    with pytest.raises(OpenCodeGoSidecarError) as excinfo:
        async with OpenCodeGoSidecarClient(_config()).stream_chat_completion({"model": "glm-5.3"}) as stream:
            async for _chunk in stream:  # pragma: no cover - must not be reached
                pass

    assert excinfo.value.status_code == 401


# --------------------------------------------------------------------------
# Session header threading (client level)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_forwards_direct_session_header(monkeypatch) -> None:
    session = _FakeSession(post_response=_FakeResponse(200, "{}"))
    _patch(monkeypatch, session)

    await OpenCodeGoSidecarClient(_config(api_key="sk-go-key")).chat_completion(
        {"model": "glm-5.3"},
        client_headers={"user-agent": "opencode/1.0", "x-opencode-session": "ses_client_value"},
    )

    assert session.last_headers["x-opencode-session"] == "ses_client_value"


@pytest.mark.asyncio
async def test_client_cannot_have_authorization_or_host_overridden(monkeypatch) -> None:
    session = _FakeSession(post_response=_FakeResponse(200, "{}"))
    _patch(monkeypatch, session)

    await OpenCodeGoSidecarClient(_config(api_key="sk-go-real")).chat_completion(
        {"model": "glm-5.3"},
        client_headers={
            "user-agent": "opencode/1.0",
            "authorization": "Bearer attacker-token",
            "host": "evil.example.com",
            "x-forwarded-for": "10.0.0.1",
        },
    )

    # The outbound header set is built from stored config; the only inbound
    # header that can influence it is the derived session id.
    assert session.last_headers["Authorization"] == "Bearer sk-go-real"
    assert "host" not in {key.lower() for key in session.last_headers}
    assert "x-forwarded-for" not in {key.lower() for key in session.last_headers}


@pytest.mark.asyncio
async def test_client_sends_no_session_header_for_unknown_client(monkeypatch) -> None:
    session = _FakeSession(post_response=_FakeResponse(200, "{}"))
    _patch(monkeypatch, session)

    await OpenCodeGoSidecarClient(_config(api_key="sk-go-key")).chat_completion(
        {"model": "glm-5.3"},
        client_headers={"user-agent": "curl/8.4.0"},
    )

    # Honest outcome: no identity is known, so none is invented.
    assert "x-opencode-session" not in {key.lower() for key in session.last_headers}


@pytest.mark.asyncio
async def test_session_header_is_not_accumulated_across_requests(monkeypatch) -> None:
    session = _FakeSession(post_response=_FakeResponse(200, "{}"))
    _patch(monkeypatch, session)
    client = OpenCodeGoSidecarClient(_config(api_key="sk-go-key"))

    await client.chat_completion(
        {"model": "glm-5.3"},
        client_headers={"user-agent": "opencode/1.0", "x-opencode-session": "first"},
    )
    await client.chat_completion({"model": "glm-5.3"}, client_headers={"user-agent": "curl/8.4.0"})

    # A reused header mapping must not carry the previous request's session.
    assert "x-opencode-session" not in {key.lower() for key in session.last_headers}


# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------


def test_sanitize_removes_configured_key_bearer_and_bare_sk() -> None:
    key = "sk-go-abcdef0123456789"
    message = f"Invalid credential {key} (Authorization: Bearer {key}) for sk-go-otherkey12345"

    sanitized = sanitize_opencode_go_message(message, api_key=key)

    assert key not in sanitized
    assert "sk-go-otherkey12345" not in sanitized
    assert "[redacted]" in sanitized


def test_sanitize_preserves_ordinary_upstream_prose() -> None:
    # A short purely-alphabetic configured value is ambiguous with prose, so it
    # is only redacted in a credential position - the message stays legible.
    assert sanitize_opencode_go_message("Invalid API key", api_key="key") == "Invalid API key"


def test_sanitize_error_body_scrubs_nested_strings() -> None:
    key = "sk-go-abcdef0123456789"
    body = {"error": {"message": f"bad {key}", "meta": [f"Bearer {key}", {"echo": key}]}}

    sanitized = sanitize_opencode_go_error_body(body, api_key=key)

    assert key not in repr(sanitized)


# --------------------------------------------------------------------------
# Client cache
# --------------------------------------------------------------------------


def test_client_cache_is_evicted_when_config_changes() -> None:
    reset_opencode_go_sidecar_client_cache()
    first = get_opencode_go_sidecar_client(_config(api_key="sk-go-one"))
    assert get_opencode_go_sidecar_client(_config(api_key="sk-go-one")) is first

    # A settings change must drop the cached client together with its cached
    # models and its copy of the old credential.
    second = get_opencode_go_sidecar_client(_config(api_key="sk-go-two"))
    assert second is not first
    reset_opencode_go_sidecar_client_cache()


# --------------------------------------------------------------------------
# Go-vs-Zen enforced on every configuration path (PR 43 review finding)
# --------------------------------------------------------------------------


class TestGoEndpointEnforcedFromEnvironment:
    """The environment must not be a way around the Go/Zen guard.

    The dashboard validator already rejected a Zen URL, but a fresh install
    seeds this column from ``CODEX_LB_OPENCODE_GO_SIDECAR_BASE_URL``. That
    second path reached the same client, which would then send the Go
    subscription key to the pay-as-you-go Zen endpoint - billing credits
    instead of the subscription, with no error anywhere.
    """

    @staticmethod
    def _settings(base_url: str):
        from app.core.config.settings import Settings

        return Settings(opencode_go_sidecar_base_url=base_url)

    def test_a_zen_base_url_from_the_environment_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="OpenCode Go endpoint"):
            self._settings("https://opencode.ai/zen/v1")

    @pytest.mark.parametrize(
        "base_url",
        [
            "https://opencode.ai/zen/v1/gold",
            "https://opencode.ai/zen/going/v1",
            "https://example.com/zen/go/v1",
            "http://opencode.ai/zen/go/v1",
        ],
        ids=["path-lookalike", "segment-lookalike", "other-host", "plaintext"],
    )
    def test_lookalike_urls_are_rejected(self, base_url: str) -> None:
        with pytest.raises(ValueError, match="OpenCode Go endpoint"):
            self._settings(base_url)

    def test_the_documented_go_url_is_accepted(self) -> None:
        assert self._settings("https://opencode.ai/zen/go/v1").opencode_go_sidecar_base_url == (
            "https://opencode.ai/zen/go/v1"
        )

    def test_static_and_dashboard_validation_share_one_predicate(self) -> None:
        """Two copies of this rule could drift; one definition cannot.

        Both validators import the same leaf predicate, so a future change to
        what counts as a Go endpoint cannot leave one entry point permissive.
        """

        from app.core.config import settings as static_settings
        from app.core.config.opencode_go_endpoint import is_opencode_go_base_url as canonical
        from app.modules.settings import schemas as dashboard_schemas

        assert static_settings.is_opencode_go_base_url is canonical
        assert dashboard_schemas.is_opencode_go_base_url is canonical


# --------------------------------------------------------------------------
# Bounded body reads (PR 46 finding 1)
# --------------------------------------------------------------------------


class TestResponseBodyIsBounded:
    """A remote party must not decide how much memory this process allocates.

    ``resp.text()`` buffers the whole body before anything can inspect its size,
    so an upstream that is hostile, misconfigured, or actually a captive portal
    could hand over an arbitrarily large body. Reproduced through the real
    client: an 8 MiB chunked listing was buffered and parsed in full.

    The cap mirrors the sibling quota client's contract rather than inventing a
    second size policy.
    """

    @pytest.mark.asyncio
    async def test_an_oversized_chunked_body_is_rejected(self, monkeypatch) -> None:
        """No ``Content-Length`` to trust, so only counted bytes can bound it."""

        from app.core.clients.opencode_go_sidecar import MAX_RESPONSE_BYTES

        oversize = b"x" * (MAX_RESPONSE_BYTES + 8192)
        _patch(monkeypatch, _FakeSession(get_response=_FakeResponse(200, "", chunks=[oversize])))

        with pytest.raises(OpenCodeGoSidecarError) as excinfo:
            await OpenCodeGoSidecarClient(_config(api_key="sk-go-key")).list_models()

        assert excinfo.value.status_code == 502
        assert "too large" in excinfo.value.message

    @pytest.mark.asyncio
    async def test_an_oversized_declared_length_is_rejected_before_reading(self, monkeypatch) -> None:
        """The advisory fast path: refuse before pulling the body at all."""

        from app.core.clients.opencode_go_sidecar import MAX_RESPONSE_BYTES

        response = _FakeResponse(200, "", headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)})
        _patch(monkeypatch, _FakeSession(get_response=response))

        with pytest.raises(OpenCodeGoSidecarError) as excinfo:
            await OpenCodeGoSidecarClient(_config(api_key="sk-go-key")).list_models()

        assert "declared over" in excinfo.value.message

    @pytest.mark.asyncio
    async def test_an_ordinary_response_still_parses(self, monkeypatch) -> None:
        """Control: the cap must not break the responses we actually serve."""

        body = b'{"object":"list","data":[{"id":"glm-5.3"},{"id":"kimi-k3"}]}'
        _patch(monkeypatch, _FakeSession(get_response=_FakeResponse(200, "", chunks=[body])))

        models = await OpenCodeGoSidecarClient(_config(api_key="sk-go-key")).list_models()

        assert [model.id for model in models] == ["glm-5.3", "kimi-k3"]

    @pytest.mark.asyncio
    async def test_a_body_split_across_chunks_is_reassembled(self, monkeypatch) -> None:
        """Counting bytes must not change how an ordinary body is decoded."""

        body = '{"object":"list","data":[{"id":"café-model"}]}'.encode("utf-8")
        cut = body.index(b"\xc3") + 1
        _patch(monkeypatch, _FakeSession(get_response=_FakeResponse(200, "", chunks=[body[:cut], body[cut:]])))

        models = await OpenCodeGoSidecarClient(_config(api_key="sk-go-key")).list_models()

        assert [model.id for model in models] == ["café-model"]


class TestTheCapDoesNotDestroyTheUpstreamStatus:
    """Bounding an *error* body must not discard what the error said.

    The cap applies to error bodies too - they are equally attacker-influenced.
    But the status line and ``Retry-After`` live in the headers, and they are
    the parts this integration acts on. Reading the body first and letting the
    cap raise would replace a 429 with a generic 502, dropping the upstream's
    own retry window; Go's caps are hard dollar limits, so a lost ``Retry-After``
    turns one rate limit into a retry storm. A 401/403 would likewise be
    downgraded to an unattributable upstream fault.

    So an oversized error body degrades to "no body" while the status survives.
    """

    @staticmethod
    def _oversized_error(status: int, headers: dict[str, str] | None = None) -> _FakeResponse:
        from app.core.clients.opencode_go_sidecar import MAX_RESPONSE_BYTES

        return _FakeResponse(status, "", chunks=[b"x" * (MAX_RESPONSE_BYTES + 8192)], headers=headers)

    @pytest.mark.asyncio
    async def test_an_oversized_429_keeps_its_status_and_retry_after(self, monkeypatch) -> None:
        _patch(monkeypatch, _FakeSession(post_response=self._oversized_error(429, {"Retry-After": "137"})))

        with pytest.raises(OpenCodeGoSidecarError) as excinfo:
            await OpenCodeGoSidecarClient(_config(api_key="sk-go-key")).chat_completion({"model": "glm-5.3"})

        assert excinfo.value.status_code == 429
        assert excinfo.value.retry_after == "137"

    @pytest.mark.asyncio
    async def test_an_oversized_401_stays_a_credential_problem(self, monkeypatch) -> None:
        """Not remapped to 502: the dashboard and caller act on this difference."""

        _patch(monkeypatch, _FakeSession(post_response=self._oversized_error(401)))

        with pytest.raises(OpenCodeGoSidecarError) as excinfo:
            await OpenCodeGoSidecarClient(_config(api_key="sk-go-key")).chat_completion({"model": "glm-5.3"})

        assert excinfo.value.status_code == 401

    @pytest.mark.asyncio
    async def test_the_oversized_error_body_itself_is_still_dropped(self, monkeypatch) -> None:
        """Preserving the status is not an excuse to relay the oversized body.

        ``client_facing_sidecar_error`` relays bodies to the caller, so the
        capped payload must not survive into the exception.
        """

        _patch(monkeypatch, _FakeSession(post_response=self._oversized_error(429, {"Retry-After": "137"})))

        with pytest.raises(OpenCodeGoSidecarError) as excinfo:
            await OpenCodeGoSidecarClient(_config(api_key="sk-go-key")).chat_completion({"model": "glm-5.3"})

        assert excinfo.value.body is None
        assert excinfo.value.message == "OpenCode Go returned HTTP 429"

    @pytest.mark.asyncio
    async def test_the_streaming_error_path_keeps_the_status_too(self, monkeypatch) -> None:
        """The third call site reads an error body before streaming begins."""

        _patch(monkeypatch, _FakeSession(post_response=self._oversized_error(429, {"Retry-After": "42"})))

        client = OpenCodeGoSidecarClient(_config(api_key="sk-go-key"))
        with pytest.raises(OpenCodeGoSidecarError) as excinfo:
            async with client.stream_chat_completion({"model": "glm-5.3"}):
                pass

        assert excinfo.value.status_code == 429
        assert excinfo.value.retry_after == "42"

    @pytest.mark.asyncio
    async def test_an_ordinary_sized_error_still_reports_its_message(self, monkeypatch) -> None:
        """Control: the degradation applies only when the cap actually trips."""

        _patch(
            monkeypatch,
            _FakeSession(post_response=_FakeResponse(400, '{"error":{"message":"bad model"}}')),
        )

        with pytest.raises(OpenCodeGoSidecarError) as excinfo:
            await OpenCodeGoSidecarClient(_config(api_key="sk-go-key")).chat_completion({"model": "glm-5.3"})

        assert excinfo.value.status_code == 400
        assert excinfo.value.message == "bad model"

    @pytest.mark.asyncio
    async def test_an_oversized_success_body_is_still_rejected(self, monkeypatch) -> None:
        """Counterfactual: the cap is not silently disabled for 2xx responses."""

        _patch(monkeypatch, _FakeSession(post_response=self._oversized_error(200)))

        with pytest.raises(OpenCodeGoSidecarError) as excinfo:
            await OpenCodeGoSidecarClient(_config(api_key="sk-go-key")).chat_completion({"model": "glm-5.3"})

        assert excinfo.value.status_code == 502
        assert "too large" in excinfo.value.message
