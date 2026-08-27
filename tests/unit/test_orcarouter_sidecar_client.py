from __future__ import annotations

import logging

import pytest

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.orcarouter_sidecar import (
    OrcaRouterSidecarClient,
    OrcaRouterSidecarConfig,
    OrcaRouterSidecarError,
    OrcaRouterSidecarUnavailableError,
    get_orcarouter_sidecar_client,
    reset_orcarouter_sidecar_client_cache,
    sanitize_orcarouter_message,
)

pytestmark = pytest.mark.unit


def _config(**overrides) -> OrcaRouterSidecarConfig:
    values = {
        "enabled": True,
        "base_url": "https://api.orcarouter.ai/v1",
        "api_key": None,
        "prefixes": (SidecarPrefix(prefix="orcarouter/", strip=False),),
        "connect_timeout_seconds": 8.0,
        "request_timeout_seconds": 600.0,
        "models_cache_ttl_seconds": 60.0,
    }
    values.update(overrides)
    return OrcaRouterSidecarConfig(**values)


class _FakeContent:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _size: int):
        for chunk in self._chunks:
            yield chunk


class _FakeResponse:
    def __init__(self, status: int, text: str, chunks: list[bytes] | None = None) -> None:
        self.status = status
        self._text = text
        self.content = _FakeContent(chunks or [])

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
        self.last_url = None
        self.last_headers = None
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


@pytest.mark.asyncio
async def test_list_models_sends_bearer_key_and_parses_models(monkeypatch) -> None:
    session = _FakeSession(
        get_response=_FakeResponse(
            200,
            '{"object":"list","data":[{"id":"orcarouter/auto","created":123,"owned_by":"deepseek"}]}',
        )
    )
    monkeypatch.setattr("app.core.clients.orcarouter_sidecar.lease_http_session", lambda: _Lease(session))
    client = OrcaRouterSidecarClient(_config(api_key="orcarouter-key"))

    models = await client.list_models()

    assert session.last_url == "https://api.orcarouter.ai/v1/models"
    assert session.last_headers["Authorization"] == "Bearer orcarouter-key"
    assert session.last_headers["User-Agent"] == "codex-lb/orcarouter-sidecar"
    assert session.last_headers["HTTP-Referer"] == "https://github.com/vitalNohj/codex-lb"
    assert session.last_headers["X-Title"] == "codex-lb"
    assert [model.id for model in models] == ["orcarouter/auto"]
    assert models[0].created == 123
    assert models[0].owned_by == "deepseek" or models[0].owned_by == "orcarouter"


@pytest.mark.asyncio
async def test_list_models_parses_pricing_and_updates_registry(monkeypatch) -> None:
    from app.core.usage.runtime_pricing import get_runtime_pricing_registry

    get_runtime_pricing_registry().clear()
    session = _FakeSession(
        get_response=_FakeResponse(
            200,
            '{"object":"list","data":['
            '{"id":"vendor/model-x","pricing":{"prompt":"0.0000008","completion":"0.000004",'
            '"input_cache_read":"0.0000002"}},'
            '{"id":"vendor/model-y","pricing":{"prompt":"bad","completion":"0.000004"}},'
            '{"id":"vendor/model-z"}'
            "]}",
        )
    )
    monkeypatch.setattr("app.core.clients.orcarouter_sidecar.lease_http_session", lambda: _Lease(session))
    client = OrcaRouterSidecarClient(_config(api_key="key"))

    models = await client.list_models()

    by_id = {model.id: model for model in models}
    assert by_id["vendor/model-x"].pricing is not None
    assert by_id["vendor/model-x"].pricing.input_per_1m == pytest.approx(0.8)
    assert by_id["vendor/model-x"].pricing.output_per_1m == pytest.approx(4.0)
    assert by_id["vendor/model-x"].pricing.cached_input_per_1m == pytest.approx(0.2)
    # Unparseable / missing pricing -> no runtime price, fetch still succeeds.
    assert by_id["vendor/model-y"].pricing is None
    assert by_id["vendor/model-z"].pricing is None

    registry = get_runtime_pricing_registry()
    assert registry.runtime_pricing_for_model("vendor/model-x") is not None
    assert registry.runtime_pricing_for_model("vendor/model-y") is None


@pytest.mark.asyncio
async def test_chat_completion_relays_error_envelope(monkeypatch) -> None:
    session = _FakeSession(
        post_response=_FakeResponse(401, '{"error":{"message":"expired","type":"authentication_error"}}')
    )
    monkeypatch.setattr("app.core.clients.orcarouter_sidecar.lease_http_session", lambda: _Lease(session))
    client = OrcaRouterSidecarClient(_config(api_key="key"))

    with pytest.raises(OrcaRouterSidecarError) as exc_info:
        await client.chat_completion({"model": "orcarouter/auto", "messages": []})

    assert exc_info.value.status_code == 401
    assert exc_info.value.message == "expired"


@pytest.mark.asyncio
async def test_transport_error_becomes_unavailable(monkeypatch) -> None:
    session = _FakeSession(get_response=OSError("boom"))
    monkeypatch.setattr("app.core.clients.orcarouter_sidecar.lease_http_session", lambda: _Lease(session))
    client = OrcaRouterSidecarClient(_config(api_key="key"))

    with pytest.raises(OrcaRouterSidecarUnavailableError):
        await client.list_models()


@pytest.fixture(autouse=True)
def _clear_orcarouter_client_cache():
    reset_orcarouter_sidecar_client_cache()
    yield
    reset_orcarouter_sidecar_client_cache()


def test_client_cache_returns_the_same_instance_for_an_unchanged_config() -> None:
    config = _config(api_key="key")

    first = get_orcarouter_sidecar_client(config)
    second = get_orcarouter_sidecar_client(_config(api_key="key"))

    # Same instance means ``list_models_cached`` keeps its TTL state, so a
    # second ``GET /v1/models`` inside the TTL costs no upstream round trip.
    assert first is second


@pytest.mark.parametrize(
    "changed",
    [
        {"api_key": "rotated-key"},
        {"base_url": "https://orca.internal/v1"},
        {"models_cache_ttl_seconds": 5.0},
        {"prefixes": (SidecarPrefix(prefix="orca-", strip=True),)},
        {"enabled": False},
    ],
)
def test_client_cache_evicts_on_any_config_change(changed) -> None:
    first = get_orcarouter_sidecar_client(_config(api_key="key"))

    second = get_orcarouter_sidecar_client(_config(**{"api_key": "key", **changed}))

    # A settings change must never be served by a client holding the old
    # credential, base URL, or cached model list.
    assert second is not first
    assert get_orcarouter_sidecar_client(_config(**{"api_key": "key", **changed})) is second


@pytest.mark.asyncio
async def test_client_cache_eviction_drops_the_previous_credential_and_models(monkeypatch) -> None:
    session = _FakeSession(get_response=_FakeResponse(200, '{"data":[{"id":"orcarouter/auto"}]}'))
    monkeypatch.setattr("app.core.clients.orcarouter_sidecar.lease_http_session", lambda: _Lease(session))

    stale = get_orcarouter_sidecar_client(_config(api_key="old-key"))
    assert await stale.list_models_cached() != []

    rotated = get_orcarouter_sidecar_client(_config(api_key="new-key"))

    assert rotated.config.api_key == "new-key"
    assert rotated._models_cache is None
    reset_orcarouter_sidecar_client_cache()
    assert get_orcarouter_sidecar_client(_config(api_key="new-key")) is not rotated


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_chat_requests_opt_into_the_orcarouter_billed_cost(monkeypatch, stream) -> None:
    """Both chat paths must send ``X-OrcaRouter-Include-Cost``.

    Absent the header OrcaRouter omits ``usage.cost_usd`` entirely, and absence
    means "not requested" rather than "free"
    (docs.orcarouter.ai/operations/per-request-cost).
    """

    session = _FakeSession(post_response=_FakeResponse(200, "{}", chunks=[b"data: [DONE]\n\n"]))
    monkeypatch.setattr("app.core.clients.orcarouter_sidecar.lease_http_session", lambda: _Lease(session))
    client = OrcaRouterSidecarClient(_config(api_key="orcarouter-key"))
    payload = {"model": "orcarouter/auto", "messages": []}

    if stream:
        async with client.stream_chat_completion(payload) as chunks:
            async for _chunk in chunks:
                pass
    else:
        await client.chat_completion(payload)

    assert session.last_headers["X-OrcaRouter-Include-Cost"] == "true"


@pytest.mark.asyncio
async def test_model_listing_also_opts_into_cost_without_changing_other_headers(monkeypatch) -> None:
    session = _FakeSession(get_response=_FakeResponse(200, '{"data":[]}'))
    monkeypatch.setattr("app.core.clients.orcarouter_sidecar.lease_http_session", lambda: _Lease(session))

    await OrcaRouterSidecarClient(_config(api_key="orcarouter-key")).list_models()

    assert session.last_headers["X-OrcaRouter-Include-Cost"] == "true"
    assert session.last_headers["Authorization"] == "Bearer orcarouter-key"
    assert session.last_headers["X-Title"] == "codex-lb"


# Not a real credential: a synthetic string shaped like an OrcaRouter key so the
# assertions below prove the sanitizer removed it.
_FAKE_ORCAROUTER_KEY = "sk-orca-NOTAREALKEY000000000"
# Not a real credential either: an opaque, credential-length synthetic value with
# no ``sk-orca-`` prefix, so only the configured-key rule can redact it. The base
# URL is operator-configurable and the stored key has no format constraint, so
# this shape is reachable in a real deployment.
_FAKE_OPAQUE_KEY = "notarealorcakey0123456789"
_ORCAROUTER_LOGGER = "app.core.clients.orcarouter_sidecar"


@pytest.mark.asyncio
async def test_models_refresh_failure_never_logs_the_credential(monkeypatch, caplog) -> None:
    """An upstream echoing the Authorization header must not leak via the log.

    ``list_models_cached`` swallows the upstream failure and logs it, so an
    ``exc_info=True`` traceback carried the raw upstream text - and with it the
    credential - into the application log, where runtime_logging redaction never
    reaches it.
    """

    leaked = f'upstream echoed {{\\"authorization\\":\\"Bearer {_FAKE_ORCAROUTER_KEY}\\"}}'
    session = _FakeSession(get_response=_FakeResponse(401, f'{{"error":{{"message":"{leaked}"}}}}'))
    monkeypatch.setattr("app.core.clients.orcarouter_sidecar.lease_http_session", lambda: _Lease(session))
    client = OrcaRouterSidecarClient(_config(api_key=_FAKE_ORCAROUTER_KEY))

    with caplog.at_level(logging.WARNING, logger=_ORCAROUTER_LOGGER):
        assert await client.list_models_cached() == []

    assert caplog.records
    assert _FAKE_ORCAROUTER_KEY not in caplog.text


@pytest.mark.asyncio
async def test_stale_models_reuse_after_failure_never_logs_the_credential(monkeypatch, caplog) -> None:
    """The cached-fallback branch logs the same upstream text and must be safe too."""

    leaked = f"Unauthorized for Authorization: Bearer {_FAKE_ORCAROUTER_KEY}"
    session = _FakeSession(get_response=_FakeResponse(200, '{"data":[{"id":"orcarouter/auto"}]}'))
    monkeypatch.setattr("app.core.clients.orcarouter_sidecar.lease_http_session", lambda: _Lease(session))
    client = OrcaRouterSidecarClient(_config(api_key=_FAKE_ORCAROUTER_KEY, models_cache_ttl_seconds=0.0))
    assert [model.id for model in await client.list_models_cached()] == ["orcarouter/auto"]

    session.get_response = _FakeResponse(401, f'{{"error":{{"message":"{leaked}"}}}}')
    with caplog.at_level(logging.WARNING, logger=_ORCAROUTER_LOGGER):
        assert [model.id for model in await client.list_models_cached()] == ["orcarouter/auto"]

    assert caplog.records
    assert _FAKE_ORCAROUTER_KEY not in caplog.text


@pytest.mark.parametrize(
    "upstream_message",
    [
        "Unauthorized for Authorization: Bearer {key}",
        "rejected header bearer {key}",
        'upstream echoed {{"authorization":"Bearer {key}"}}',
        "BEARER  {key}!",
        "Invalid API key: {key}",
        "{key}",
    ],
)
def test_sanitizer_removes_a_credential_shaped_configured_key(upstream_message) -> None:
    sanitized = sanitize_orcarouter_message(
        upstream_message.format(key=_FAKE_ORCAROUTER_KEY),
        api_key=_FAKE_ORCAROUTER_KEY,
    )

    assert _FAKE_ORCAROUTER_KEY not in sanitized
    assert "[redacted]" in sanitized


def test_sanitizer_keeps_the_json_structure_around_an_echoed_header() -> None:
    sanitized = sanitize_orcarouter_message(
        f'{{"authorization":"Bearer {_FAKE_ORCAROUTER_KEY}"}}',
        api_key=_FAKE_ORCAROUTER_KEY,
    )

    assert sanitized == '{"authorization":"Bearer [redacted]"}'


@pytest.mark.parametrize(
    "message",
    [
        "Invalid API key",
        "monkey business upstream",
        "keyboard interrupt while streaming",
    ],
)
def test_sanitizer_leaves_ordinary_text_untouched_for_a_non_credential_key(message) -> None:
    """A short configured value must not be scrubbed out of unrelated prose."""

    assert sanitize_orcarouter_message(message, api_key="key") == message


def test_sanitizer_still_redacts_a_short_configured_key_in_a_credential_position() -> None:
    """Even a weak configured value is a secret where it is presented as one."""

    assert sanitize_orcarouter_message("Authorization: key", api_key="key") == "Authorization: [redacted]"
    assert sanitize_orcarouter_message("Bearer key", api_key="key") == "Bearer [redacted]"


@pytest.mark.parametrize(
    "upstream_message",
    [
        "invalid api_key={key}",
        "Invalid credential {key}.",
        "rejected ?key={key}",
        "rejected ({key}), retry",
        "a,{key};b",
        "<{key}>",
        "'{key}'",
        '{{"key":"{key}"}}',
        "upstream echoed {key}",
    ],
)
def test_sanitizer_redacts_an_opaque_configured_key_next_to_punctuation(upstream_message) -> None:
    """Punctuation delimits a credential; it must not shield one from redaction.

    A configured key with no ``sk-orca-`` prefix is only covered by the
    configured-key rule. Treating '=', '.', quotes and brackets as token
    characters left the raw key in ``request_logs.error_message`` and in the body
    handed back to the calling API key.
    """

    sanitized = sanitize_orcarouter_message(
        upstream_message.format(key=_FAKE_OPAQUE_KEY),
        api_key=_FAKE_OPAQUE_KEY,
    )

    assert _FAKE_OPAQUE_KEY not in sanitized
    assert "[redacted]" in sanitized


@pytest.mark.parametrize(
    "upstream_message",
    [
        "prefix{key}",
        "x{key}y",
        "{key}suffix",
    ],
)
def test_sanitizer_leaves_an_interior_substring_of_a_longer_word_alone(upstream_message) -> None:
    """An alphanumeric neighbour means this is a longer word, not the credential."""

    message = upstream_message.format(key=_FAKE_OPAQUE_KEY)

    assert sanitize_orcarouter_message(message, api_key=_FAKE_OPAQUE_KEY) == message


# Not a real credential: a synthetic colon-delimited value, the shape schemes
# that namespace their keys ("<env>:<id>:<secret>") issue. ':' is outside the
# token character class used for boundary detection, so this pins that the
# "is it a secret" decision does not depend on that class.
_FAKE_PUNCTUATED_KEY = "notarealorca:live:0123456789abcdef"


@pytest.mark.parametrize(
    "upstream_message",
    [
        "Invalid credential {key} for project",
        "invalid api_key={key}",
        "Invalid credential {key}.",
        '{{"authorization":"Bearer {key}"}}',
        "rejected ({key}), retry",
        "{key}",
    ],
)
def test_sanitizer_redacts_a_configured_key_containing_punctuation(upstream_message) -> None:
    """A configured key is a secret whatever characters it happens to contain.

    Gating redaction on the key matching the token character class dropped every
    colon-delimited key out of the configured-key rule entirely, and truncated
    the ``Bearer`` match at the first ':' so the key's tail survived.
    """

    sanitized = sanitize_orcarouter_message(
        upstream_message.format(key=_FAKE_PUNCTUATED_KEY),
        api_key=_FAKE_PUNCTUATED_KEY,
    )

    assert _FAKE_PUNCTUATED_KEY not in sanitized
    assert "0123456789abcdef" not in sanitized
    assert "[redacted]" in sanitized


def test_bearer_rule_redacts_a_punctuated_token_without_any_configured_key() -> None:
    """The pattern rules stay unconditional, including for a rotated-away key."""

    sanitized = sanitize_orcarouter_message(
        f'{{"authorization":"Bearer {_FAKE_PUNCTUATED_KEY}"}}',
        api_key=None,
    )

    assert sanitized == '{"authorization":"Bearer [redacted]"}'
