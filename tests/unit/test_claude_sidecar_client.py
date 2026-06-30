from __future__ import annotations

import json

import pytest

from app.core.clients.claude_sidecar import (
    ClaudeSidecarClient,
    ClaudeSidecarConfig,
    ClaudeSidecarError,
    ClaudeSidecarUnavailableError,
    SidecarPrefix,
)

pytestmark = pytest.mark.unit



def _config(**overrides) -> ClaudeSidecarConfig:
    values = {
        "enabled": True,
        "base_url": "http://127.0.0.1:8317",
        "api_key": None,
        "prefixes": (SidecarPrefix(prefix="claude", strip=False),),
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
        put_response: _FakeResponse | Exception | None = None,
        patch_response: _FakeResponse | Exception | None = None,
    ) -> None:
        self.get_response = get_response
        self.post_response = post_response
        self.put_response = put_response
        self.patch_response = patch_response
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
        return self._request_with_json("post_response", url, headers=headers, json=json)

    def put(self, url: str, *, headers, json, timeout):
        return self._request_with_json("put_response", url, headers=headers, json=json)

    def patch(self, url: str, *, headers, json, timeout):
        return self._request_with_json("patch_response", url, headers=headers, json=json)

    def _request_with_json(self, response_attr: str, url: str, *, headers, json):
        self.last_url = url
        self.last_headers = headers
        self.last_json = json
        response = getattr(self, response_attr)
        if isinstance(response, Exception):
            raise response
        assert response is not None
        return response


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
async def test_get_routing_strategy_uses_management_key(monkeypatch) -> None:
    session = _FakeSession(
        get_response=_FakeResponse(200, json.dumps({'strategy': 'fill-first'}))
    )
    monkeypatch.setattr('app.core.clients.claude_sidecar.lease_http_session', lambda: _Lease(session))
    client = ClaudeSidecarClient(_config(management_key='mgmt'))

    strategy = await client.get_routing_strategy()

    assert strategy == 'fill-first'
    assert session.last_url == 'http://127.0.0.1:8317/v0/management/routing/strategy'
    assert session.last_headers['Authorization'] == 'Bearer mgmt'


@pytest.mark.asyncio
async def test_set_routing_strategy_sends_value(monkeypatch) -> None:
    session = _FakeSession(
        put_response=_FakeResponse(200, json.dumps({'status': 'ok'}))
    )
    monkeypatch.setattr('app.core.clients.claude_sidecar.lease_http_session', lambda: _Lease(session))
    client = ClaudeSidecarClient(_config(management_key='mgmt'))

    strategy = await client.set_routing_strategy('fill-first')

    assert strategy == 'fill-first'
    assert session.last_url == 'http://127.0.0.1:8317/v0/management/routing/strategy'
    assert session.last_headers['Authorization'] == 'Bearer mgmt'
    assert session.last_json == {'value': 'fill-first'}


@pytest.mark.asyncio
async def test_patch_auth_file_priority_sends_name_and_priority(monkeypatch) -> None:
    session = _FakeSession(
        patch_response=_FakeResponse(200, json.dumps({'status': 'ok'}))
    )
    monkeypatch.setattr('app.core.clients.claude_sidecar.lease_http_session', lambda: _Lease(session))
    client = ClaudeSidecarClient(_config(management_key='mgmt'))

    await client.patch_auth_file_priority('claude-x.json', 100)

    assert session.last_url == 'http://127.0.0.1:8317/v0/management/auth-files/fields'
    assert session.last_headers['Authorization'] == 'Bearer mgmt'
    assert session.last_json == {'name': 'claude-x.json', 'priority': 100}


@pytest.mark.asyncio
async def test_patch_auth_file_priority_relays_not_found(monkeypatch) -> None:
    session = _FakeSession(
        patch_response=_FakeResponse(404, json.dumps({'error': 'auth file not found'}))
    )
    monkeypatch.setattr('app.core.clients.claude_sidecar.lease_http_session', lambda: _Lease(session))
    client = ClaudeSidecarClient(_config(management_key='mgmt'))

    with pytest.raises(ClaudeSidecarError) as exc_info:
        await client.patch_auth_file_priority('missing.json', 100)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_pop_usage_queue_uses_management_key_and_count(monkeypatch) -> None:
    session = _FakeSession(
        get_response=_FakeResponse(
            200,
            '[{"timestamp":"2026-05-05T12:00:00Z","request_id":"req_1","tokens":{"total_tokens":30}}]',
        )
    )
    monkeypatch.setattr("app.core.clients.claude_sidecar.lease_http_session", lambda: _Lease(session))
    client = ClaudeSidecarClient(_config(api_key="api", management_key="mgmt"))

    records = await client.pop_usage_queue(10)

    assert session.last_headers["Authorization"] == "Bearer mgmt"
    assert session.last_url == "http://127.0.0.1:8317/v0/management/usage-queue?count=10"
    assert records[0]["request_id"] == "req_1"


@pytest.mark.asyncio
async def test_pop_usage_queue_returns_error_for_unauthorized(monkeypatch) -> None:
    session = _FakeSession(get_response=_FakeResponse(401, '{"error":{"message":"bad key"}}'))
    monkeypatch.setattr("app.core.clients.claude_sidecar.lease_http_session", lambda: _Lease(session))
    client = ClaudeSidecarClient(_config(management_key="bad"))

    with pytest.raises(ClaudeSidecarError) as exc_info:
        await client.pop_usage_queue(10)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_pop_usage_queue_rejects_non_array_response(monkeypatch) -> None:
    session = _FakeSession(get_response=_FakeResponse(200, '{"records":[]}'))
    monkeypatch.setattr("app.core.clients.claude_sidecar.lease_http_session", lambda: _Lease(session))
    client = ClaudeSidecarClient(_config(management_key="mgmt"))

    with pytest.raises(ClaudeSidecarError) as exc_info:
        await client.pop_usage_queue(10)
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_pop_usage_queue_transport_failure_unavailable(monkeypatch) -> None:
    session = _FakeSession(get_response=OSError("boom"))
    monkeypatch.setattr("app.core.clients.claude_sidecar.lease_http_session", lambda: _Lease(session))
    client = ClaudeSidecarClient(_config(management_key="mgmt"))

    with pytest.raises(ClaudeSidecarUnavailableError):
        await client.pop_usage_queue(10)


@pytest.mark.asyncio
async def test_api_call_posts_passthrough_and_returns_body_json(monkeypatch) -> None:
    session = _FakeSession(
        post_response=_FakeResponse(
            200,
            '{"status_code":200,"body":"{\\"five_hour\\":{\\"utilization\\":0.25}}"}',
        )
    )
    monkeypatch.setattr("app.core.clients.claude_sidecar.lease_http_session", lambda: _Lease(session))
    client = ClaudeSidecarClient(_config(management_key="mgmt"))

    body = await client.api_call(
        auth_index="0",
        method="GET",
        url="https://api.anthropic.com/api/oauth/usage",
        header={"Authorization": "Bearer $TOKEN$", "anthropic-beta": "oauth-2025-04-20"},
    )

    assert session.last_headers["Authorization"] == "Bearer mgmt"
    assert session.last_json["auth_index"] == "0"
    assert session.last_json["url"] == "https://api.anthropic.com/api/oauth/usage"
    assert session.last_json["header"]["Authorization"] == "Bearer $TOKEN$"
    assert body == {"five_hour": {"utilization": 0.25}}


@pytest.mark.asyncio
async def test_api_call_upstream_4xx_becomes_error(monkeypatch) -> None:
    session = _FakeSession(
        post_response=_FakeResponse(200, '{"status_code":429,"body":"rate limited"}')
    )
    monkeypatch.setattr("app.core.clients.claude_sidecar.lease_http_session", lambda: _Lease(session))
    client = ClaudeSidecarClient(_config(management_key="mgmt"))

    with pytest.raises(ClaudeSidecarError) as exc_info:
        await client.api_call(
            auth_index="0",
            method="GET",
            url="https://api.anthropic.com/api/oauth/usage",
            header={"Authorization": "Bearer $TOKEN$"},
        )
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_api_call_transport_failure_unavailable(monkeypatch) -> None:
    session = _FakeSession(post_response=OSError("boom"))
    monkeypatch.setattr("app.core.clients.claude_sidecar.lease_http_session", lambda: _Lease(session))
    client = ClaudeSidecarClient(_config(management_key="mgmt"))

    with pytest.raises(ClaudeSidecarUnavailableError):
        await client.api_call(
            auth_index="0",
            method="GET",
            url="https://api.anthropic.com/api/oauth/usage",
            header={"Authorization": "Bearer $TOKEN$"},
        )


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
