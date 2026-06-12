from __future__ import annotations

import pytest

from app.core.clients.omniroute_sidecar import (
    OmniRouteSidecarClient,
    OmniRouteSidecarConfig,
    OmniRouteSidecarError,
    OmniRouteSidecarUnavailableError,
)

pytestmark = pytest.mark.unit


def _config(**overrides) -> OmniRouteSidecarConfig:
    values = {
        "enabled": True,
        "base_url": "http://127.0.0.1:20128/v1",
        "api_key": None,
        "selected_models": ("omniroute/test-chat",),
        "connect_timeout_seconds": 8.0,
        "request_timeout_seconds": 600.0,
        "models_cache_ttl_seconds": 60.0,
    }
    values.update(overrides)
    return OmniRouteSidecarConfig(**values)


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
            '{"object":"list","data":[{"id":"omniroute/test-chat","created":123,"owned_by":"omniroute"}]}',
        )
    )
    monkeypatch.setattr("app.core.clients.omniroute_sidecar.lease_http_session", lambda: _Lease(session))
    client = OmniRouteSidecarClient(_config(api_key="omniroute-key"))

    models = await client.list_models()

    assert session.last_url == "http://127.0.0.1:20128/v1/models"
    assert session.last_headers["Authorization"] == "Bearer omniroute-key"
    assert session.last_headers["User-Agent"] == "codex-lb/omniroute-sidecar"
    assert [model.id for model in models] == ["omniroute/test-chat"]
    assert models[0].created == 123


@pytest.mark.asyncio
async def test_chat_completion_relays_error_envelope(monkeypatch) -> None:
    session = _FakeSession(
        post_response=_FakeResponse(401, '{"error":{"message":"expired","type":"authentication_error"}}')
    )
    monkeypatch.setattr("app.core.clients.omniroute_sidecar.lease_http_session", lambda: _Lease(session))
    client = OmniRouteSidecarClient(_config(api_key="key"))

    with pytest.raises(OmniRouteSidecarError) as exc_info:
        await client.chat_completion({"model": "omniroute/test-chat", "messages": []})

    assert exc_info.value.status_code == 401
    assert exc_info.value.message == "expired"
    assert session.last_url == "http://127.0.0.1:20128/v1/chat/completions"


@pytest.mark.asyncio
async def test_transport_error_becomes_unavailable(monkeypatch) -> None:
    session = _FakeSession(get_response=OSError("boom"))
    monkeypatch.setattr("app.core.clients.omniroute_sidecar.lease_http_session", lambda: _Lease(session))
    client = OmniRouteSidecarClient(_config(api_key="key"))

    with pytest.raises(OmniRouteSidecarUnavailableError):
        await client.list_models()
