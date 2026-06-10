from __future__ import annotations

import pytest

from app.core.clients.claude_sidecar import (
    ClaudeSidecarClient,
    ClaudeSidecarConfig,
    ClaudeSidecarError,
    ClaudeSidecarUnavailableError,
)

pytestmark = pytest.mark.unit



def _config(**overrides) -> ClaudeSidecarConfig:
    values = {
        "enabled": True,
        "base_url": "http://127.0.0.1:8317",
        "api_key": None,
        "model_prefixes": ("claude",),
        "connect_timeout_seconds": 8.0,
        "request_timeout_seconds": 600.0,
        "models_cache_ttl_seconds": 60.0,
    }
    values.update(overrides)
    return ClaudeSidecarConfig(**values)


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
        self.last_headers = None
        self.last_json = None

    def get(self, _url: str, *, headers, timeout):
        self.last_headers = headers
        if isinstance(self.get_response, Exception):
            raise self.get_response
        assert self.get_response is not None
        return self.get_response

    def post(self, _url: str, *, headers, json, timeout):
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
            '{"object":"list","data":[{"id":"claude-sonnet","created":123,"owned_by":"anthropic"}]}',
        )
    )
    monkeypatch.setattr("app.core.clients.claude_sidecar.lease_http_session", lambda: _Lease(session))
    client = ClaudeSidecarClient(_config(api_key="sidecar-key"))

    models = await client.list_models()

    assert session.last_headers["Authorization"] == "Bearer sidecar-key"
    assert [model.id for model in models] == ["claude-sonnet"]
    assert models[0].created == 123


@pytest.mark.asyncio
async def test_chat_completion_relays_error_envelope(monkeypatch) -> None:
    session = _FakeSession(
        post_response=_FakeResponse(401, '{"error":{"message":"expired","type":"authentication_error"}}')
    )
    monkeypatch.setattr("app.core.clients.claude_sidecar.lease_http_session", lambda: _Lease(session))
    client = ClaudeSidecarClient(_config())

    with pytest.raises(ClaudeSidecarError) as exc_info:
        await client.chat_completion({"model": "claude-sonnet", "messages": []})

    assert exc_info.value.status_code == 401
    assert exc_info.value.message == "expired"


@pytest.mark.asyncio
async def test_transport_error_becomes_unavailable(monkeypatch) -> None:
    session = _FakeSession(get_response=OSError("boom"))
    monkeypatch.setattr("app.core.clients.claude_sidecar.lease_http_session", lambda: _Lease(session))
    client = ClaudeSidecarClient(_config())

    with pytest.raises(ClaudeSidecarUnavailableError):
        await client.list_models()


@pytest.mark.asyncio
async def test_list_auth_files_uses_management_key_and_parses_files(monkeypatch) -> None:
    session = _FakeSession(
        get_response=_FakeResponse(
            200,
            '{"files":[{"provider":"claude","email":"a@example.com"},{"provider":"openai","email":"b@example.com"}]}',
        )
    )
    monkeypatch.setattr("app.core.clients.claude_sidecar.lease_http_session", lambda: _Lease(session))
    client = ClaudeSidecarClient(_config(api_key="api", management_key="mgmt"))

    files = await client.list_auth_files()

    assert session.last_headers["Authorization"] == "Bearer mgmt"
    assert [entry["email"] for entry in files] == ["a@example.com", "b@example.com"]


@pytest.mark.asyncio
async def test_list_auth_files_returns_error_for_unauthorized(monkeypatch) -> None:
    session = _FakeSession(get_response=_FakeResponse(401, '{"error":{"message":"bad key"}}'))
    monkeypatch.setattr("app.core.clients.claude_sidecar.lease_http_session", lambda: _Lease(session))
    client = ClaudeSidecarClient(_config(management_key="bad"))

    with pytest.raises(ClaudeSidecarError) as exc_info:
        await client.list_auth_files()
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_list_auth_files_transport_failure_unavailable(monkeypatch) -> None:
    session = _FakeSession(get_response=OSError("boom"))
    monkeypatch.setattr("app.core.clients.claude_sidecar.lease_http_session", lambda: _Lease(session))
    client = ClaudeSidecarClient(_config(management_key="mgmt"))

    with pytest.raises(ClaudeSidecarUnavailableError):
        await client.list_auth_files()


@pytest.mark.asyncio
async def test_models_cache_serves_last_good_after_refresh_failure(monkeypatch) -> None:
    client = ClaudeSidecarClient(_config(models_cache_ttl_seconds=0))
    calls = 0

    async def list_models():
        nonlocal calls
        calls += 1
        if calls == 1:
            return [type("Model", (), {"id": "claude-sonnet"})()]
        raise ClaudeSidecarUnavailableError("down")

    monkeypatch.setattr(client, "list_models", list_models)

    first = await client.list_models_cached()
    second = await client.list_models_cached()

    assert [model.id for model in first] == ["claude-sonnet"]
    assert [model.id for model in second] == ["claude-sonnet"]
