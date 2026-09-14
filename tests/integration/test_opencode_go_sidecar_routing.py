"""End-to-end routing for OpenCode Go over the real local API paths.

Every upstream here is a mock. No real OpenCode Go credential exists in this
lane and none is read from the environment, so the live facts these tests
cannot establish - real inference, real streaming, a real 429 shape, and whether
Go accepts the derived ``ses_...`` value for cache affinity - are recorded as
validation limits in the task handoff rather than asserted here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from sqlalchemy import select

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.opencode_go_sidecar import (
    OpenCodeGoSidecarConfig,
    OpenCodeGoSidecarError,
    OpenCodeGoSidecarUnavailableError,
)
from app.core.config.settings import get_settings
from app.db.models import ApiKeyUsageReservation, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService, LimitRuleInput

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class _FakeModel:
    id: str
    created: int | None = 1789353162
    owned_by: str | None = "opencode"


class _FakeStreamContext:
    def __init__(self, error: Exception | None, *, chunks: list[bytes] | None = None) -> None:
        self.error = error
        self.chunks = chunks

    async def __aenter__(self):
        if self.error is not None:
            raise self.error

        default = [
            b'data: {"id":"chunk-1","object":"chat.completion.chunk",'
            b'"choices":[{"delta":{"content":"hi"}}]}\n\n',
            b'data: {"id":"chunk-2","object":"chat.completion.chunk","choices":[],'
            b'"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n',
            b"data: [DONE]\n\n",
        ]
        payload = self.chunks if self.chunks is not None else default

        async def chunks():
            for chunk in payload:
                yield chunk

        return chunks()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeOpenCodeGoClient:
    def __init__(self, config: OpenCodeGoSidecarConfig) -> None:
        self.config = config
        self.chat_payloads: list[dict] = []
        self.stream_payloads: list[dict] = []
        self.chat_headers: list[dict | None] = []
        self.stream_headers: list[dict | None] = []
        # The live Go listing mixes all three upstream protocols. Include one of
        # each so advertisement filtering is exercised against a realistic set.
        self.models = [
            _FakeModel("glm-5.3"),
            _FakeModel("kimi-k3"),
            _FakeModel("qwen3.7-plus"),
            _FakeModel("grok-4.6"),
            _FakeModel("muse-spark-1.3-contributor"),
        ]
        self.chat_error: Exception | None = None
        self.stream_error: Exception | None = None
        self.stream_chunks: list[bytes] | None = None

    async def list_models(self):
        return self.models

    async def list_models_cached(self):
        return self.models

    async def chat_completion(self, payload, *, client_headers=None):
        self.chat_payloads.append(dict(payload))
        self.chat_headers.append(dict(client_headers) if client_headers is not None else None)
        if self.chat_error is not None:
            raise self.chat_error
        return {
            "id": "chatcmpl-opencode-go",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    def stream_chat_completion(self, payload, *, client_headers=None):
        self.stream_payloads.append(dict(payload))
        self.stream_headers.append(dict(client_headers) if client_headers is not None else None)
        return _FakeStreamContext(self.stream_error, chunks=self.stream_chunks)


@pytest.fixture
async def opencode_go_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_OPENCODE_GO_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def fake_opencode_go(monkeypatch):
    config = OpenCodeGoSidecarConfig(
        enabled=True,
        base_url="https://opencode.ai/zen/go/v1",
        api_key="sk-go-test-key",
        prefixes=(SidecarPrefix(prefix="opencode-go/", strip=True),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=("glm-5.3", "qwen3.7-plus", "grok-4.6"),
    )
    client = _FakeOpenCodeGoClient(config)

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_opencode_go_sidecar_config", load_config)
    monkeypatch.setattr("app.modules.proxy.api.OpenCodeGoSidecarClient", lambda _config: client)
    monkeypatch.setattr("app.modules.proxy.api.get_opencode_go_sidecar_client", lambda _config: client)
    return client


async def _settings_payload(async_client) -> None:
    response = await async_client.put(
        "/api/settings",
        json={
            "opencodeGoSidecarEnabled": True,
            "opencodeGoSidecarApiKey": "sk-go-test-key",
            "opencodeGoSidecarModelPrefixes": ["opencode-go/"],
            "opencodeGoSidecarFullModels": ["glm-5.3", "qwen3.7-plus", "grok-4.6"],
        },
    )
    assert response.status_code == 200


async def _enable_api_key_auth(async_client) -> None:
    response = await async_client.put("/api/settings", json={"apiKeyAuthEnabled": True})
    assert response.status_code == 200


async def _create_api_key(name: str, *, limits: list[LimitRuleInput] | None = None):
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        return await service.create_key(ApiKeyCreateData(name=name, allowed_models=None, limits=limits or []))


async def _reservation_statuses() -> list[str]:
    async with SessionLocal() as session:
        result = await session.execute(select(ApiKeyUsageReservation.status))
        return list(result.scalars().all())


async def _go_logs() -> list[RequestLog]:
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    return [log for log in logs if log.source == "opencode_go_sidecar"]


# --------------------------------------------------------------------------
# Defaults
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_and_unconfigured_by_default(async_client):
    response = await async_client.get("/api/settings")

    assert response.status_code == 200
    body = response.json()
    assert body["opencodeGoSidecarEnabled"] is False
    assert body["opencodeGoSidecarApiKeyConfigured"] is False
    assert body["opencodeGoSidecarBaseUrl"] == "https://opencode.ai/zen/go/v1"


@pytest.mark.asyncio
async def test_status_endpoint_reports_disabled_before_configuration(async_client):
    response = await async_client.get("/api/opencode-go-sidecar/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "disabled"
    assert body["enabled"] is False
    assert body["configured"] is False


@pytest.mark.asyncio
async def test_models_endpoint_makes_no_upstream_call_while_disabled(async_client, fake_opencode_go):
    response = await async_client.get("/api/opencode-go-sidecar/models")

    assert response.status_code == 200
    # Merely opening Settings must not originate traffic to a subscription the
    # operator has not turned on.
    assert response.json()["models"] == []


# --------------------------------------------------------------------------
# Settings persistence and validation
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settings_round_trip_never_returns_the_api_key(async_client, opencode_go_enabled):
    await _settings_payload(async_client)

    body = (await async_client.get("/api/settings")).json()

    assert body["opencodeGoSidecarEnabled"] is True
    assert body["opencodeGoSidecarApiKeyConfigured"] is True
    assert body["opencodeGoSidecarFullModels"] == ["glm-5.3", "qwen3.7-plus", "grok-4.6"]
    # Not masked, not truncated - simply never present in any shape.
    assert "sk-go-test-key" not in json.dumps(body)
    assert "opencodeGoSidecarApiKey" not in body


@pytest.mark.asyncio
async def test_zen_base_url_is_rejected(async_client, opencode_go_enabled):
    # Go and Zen are different products; a Go key on the Zen path bills
    # pay-as-you-go credits instead of the subscription.
    response = await async_client.put(
        "/api/settings",
        json={"opencodeGoSidecarEnabled": True, "opencodeGoSidecarBaseUrl": "https://opencode.ai/zen/v1"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_prefix_conflict_with_another_integration_is_rejected(async_client, opencode_go_enabled):
    response = await async_client.put(
        "/api/settings",
        json={
            "opencodeGoSidecarModelPrefixes": ["shared/"],
            "orcarouterSidecarModelPrefixes": ["shared/"],
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "sidecar_routing_conflict"


@pytest.mark.asyncio
async def test_clear_api_key_removes_the_stored_credential(async_client, opencode_go_enabled):
    await _settings_payload(async_client)

    await async_client.put("/api/settings", json={"opencodeGoSidecarClearApiKey": True})

    assert (await async_client.get("/api/settings")).json()["opencodeGoSidecarApiKeyConfigured"] is False


# --------------------------------------------------------------------------
# Chat dispatch
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_stream_routes_and_finalizes_reservation(async_client, opencode_go_enabled, fake_opencode_go):
    await _settings_payload(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "go-key",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)],
    )

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}", "user-agent": "opencode/1.0"},
        json={"model": "opencode-go/glm-5.3", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "hi"
    # The configured prefix is an alias and must be stripped before the wire
    # model reaches the upstream.
    assert fake_opencode_go.chat_payloads[0]["model"] == "glm-5.3"
    assert await _reservation_statuses() == ["finalized"]

    logs = await _go_logs()
    assert len(logs) == 1
    assert logs[0].status == "success"
    assert logs[0].input_tokens == 10
    assert logs[0].output_tokens == 5


@pytest.mark.asyncio
async def test_stream_routes_and_relays_sse(async_client, opencode_go_enabled, fake_opencode_go):
    await _settings_payload(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("go-key")

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}", "user-agent": "opencode/1.0"},
        json={"model": "opencode-go/glm-5.3", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    )

    assert response.status_code == 200
    text = response.text
    assert '"content":"hi"' in text
    assert "data: [DONE]" in text
    # Usage must be requested or the pricing module gets no tokens for a
    # streamed request.
    assert fake_opencode_go.stream_payloads[0]["stream_options"] == {"include_usage": True}

    logs = await _go_logs()
    assert logs[0].status == "success"
    assert logs[0].input_tokens == 10


@pytest.mark.asyncio
async def test_stream_tool_calls_survive_the_hop(async_client, opencode_go_enabled, fake_opencode_go):
    fake_opencode_go.stream_chunks = [
        b'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"delta":{"tool_calls":'
        b'[{"index":0,"id":"call_abc","type":"function",'
        b'"function":{"name":"read_file","arguments":"{\\"path\\":\\"a.py\\"}"}}]}}]}\n\n',
        b'data: {"id":"c2","object":"chat.completion.chunk","choices":[],'
        b'"usage":{"prompt_tokens":7,"completion_tokens":3}}\n\n',
        b"data: [DONE]\n\n",
    ]
    await _settings_payload(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("go-key")

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}", "user-agent": "opencode/1.0"},
        json={
            "model": "opencode-go/glm-5.3",
            "messages": [{"role": "user", "content": "read a.py"}],
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "read_file", "parameters": {"type": "object", "properties": {}}},
                }
            ],
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert "call_abc" in response.text
    assert "read_file" in response.text
    assert fake_opencode_go.stream_payloads[0]["tools"][0]["function"]["name"] == "read_file"


# --------------------------------------------------------------------------
# Model advertisement
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_list_advertises_only_dispatchable_models(async_client, opencode_go_enabled, fake_opencode_go):
    await _settings_payload(async_client)

    response = await async_client.get("/v1/models")

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["data"]}
    assert "glm-5.3" in ids
    # Pinned by the operator but served by Go on endpoints this build does not
    # speak, so they must not be advertised as available.
    assert "qwen3.7-plus" not in ids
    assert "grok-4.6" not in ids


@pytest.mark.asyncio
async def test_dashboard_models_endpoint_annotates_protocol_and_support(async_client, monkeypatch, fake_opencode_go):
    monkeypatch.setattr(
        "app.modules.opencode_go_sidecar.service.get_opencode_go_sidecar_client",
        lambda _config: fake_opencode_go,
    )
    await _settings_payload(async_client)

    response = await async_client.get("/api/opencode-go-sidecar/models")

    assert response.status_code == 200
    by_id = {model["id"]: model for model in response.json()["models"]}
    assert by_id["glm-5.3"]["protocol"] == "chat_completions"
    assert by_id["glm-5.3"]["supported"] is True
    # Listed, annotated, and visibly unavailable - not hidden and not offered.
    assert by_id["qwen3.7-plus"]["protocol"] == "messages"
    assert by_id["qwen3.7-plus"]["supported"] is False
    assert by_id["grok-4.6"]["protocol"] == "responses"
    assert by_id["grok-4.6"]["supported"] is False
    # A privacy-sensitive model is never reported supported.
    assert by_id["muse-spark-1.3-contributor"]["supported"] is False


@pytest.mark.asyncio
async def test_unsupported_model_request_is_refused_with_an_explanation(
    async_client, opencode_go_enabled, fake_opencode_go
):
    await _settings_payload(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("go-key")

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}", "user-agent": "opencode/1.0"},
        json={"model": "opencode-go/qwen3.7-plus", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "opencode_go_model_unsupported"
    # No request reached the paid subscription.
    assert fake_opencode_go.chat_payloads == []


# --------------------------------------------------------------------------
# Session identity across turns and clients
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_identity_is_stable_across_turns(async_client, opencode_go_enabled, fake_opencode_go):
    await _settings_payload(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("go-key")
    headers = {
        "Authorization": f"Bearer {key.key}",
        "user-agent": "opencode/1.0",
        "x-session-id": "conversation-77",
    }

    for turn in ("first", "second"):
        response = await async_client.post(
            "/v1/chat/completions",
            headers=headers,
            json={"model": "opencode-go/glm-5.3", "messages": [{"role": "user", "content": turn}]},
        )
        assert response.status_code == 200

    from app.core.conversation.opencode_go_session import resolve_opencode_go_session_id

    resolved = [resolve_opencode_go_session_id(h) for h in fake_opencode_go.chat_headers]
    assert resolved[0] is not None
    assert resolved[0] == resolved[1]
    assert resolved[0].startswith("ses_")
    # The client's raw identifier never reaches the upstream.
    assert "conversation-77" not in resolved[0]


@pytest.mark.asyncio
async def test_two_clients_reusing_one_raw_id_stay_isolated(async_client, opencode_go_enabled, fake_opencode_go):
    await _settings_payload(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("go-key")

    for agent, header in (("opencode/1.0", "x-session-id"), ("codex_cli_rs/1.0", "thread-id")):
        response = await async_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key.key}", "user-agent": agent, header: "shared-raw-id"},
            json={"model": "opencode-go/glm-5.3", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 200

    from app.core.conversation.opencode_go_session import resolve_opencode_go_session_id

    resolved = [resolve_opencode_go_session_id(h) for h in fake_opencode_go.chat_headers]
    assert resolved[0] is not None and resolved[1] is not None
    assert resolved[0] != resolved[1]


@pytest.mark.asyncio
async def test_unknown_client_gets_no_session_header(async_client, opencode_go_enabled, fake_opencode_go):
    await _settings_payload(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("go-key")

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}", "user-agent": "curl/8.4.0"},
        json={"model": "opencode-go/glm-5.3", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    from app.core.conversation.opencode_go_session import resolve_opencode_go_session_id

    # Documented compatibility outcome: no identity known, so none invented.
    assert resolve_opencode_go_session_id(fake_opencode_go.chat_headers[0]) is None


# --------------------------------------------------------------------------
# Error handling
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upstream_401_becomes_503_and_releases_reservation(
    async_client, opencode_go_enabled, fake_opencode_go
):
    fake_opencode_go.chat_error = OpenCodeGoSidecarError(
        401, "Missing API key.", body={"error": {"message": "Missing API key."}}
    )
    await _settings_payload(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key(
        "go-key",
        limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1000)],
    )

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}", "user-agent": "opencode/1.0"},
        json={"model": "opencode-go/glm-5.3", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "60"
    assert await _reservation_statuses() != ["active"]


@pytest.mark.asyncio
async def test_upstream_429_relays_status_and_retry_after(async_client, opencode_go_enabled, fake_opencode_go):
    fake_opencode_go.chat_error = OpenCodeGoSidecarError(
        429,
        "Rate limit reached",
        body={"error": {"message": "Rate limit reached"}},
        retry_after="321",
    )
    await _settings_payload(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("go-key")

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}", "user-agent": "opencode/1.0"},
        json={"model": "opencode-go/glm-5.3", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "321"


@pytest.mark.asyncio
async def test_upstream_unavailable_becomes_503(async_client, opencode_go_enabled, fake_opencode_go):
    fake_opencode_go.chat_error = OpenCodeGoSidecarUnavailableError("connection refused")
    await _settings_payload(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("go-key")

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}", "user-agent": "opencode/1.0"},
        json={"model": "opencode-go/glm-5.3", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "opencode_go_sidecar_unavailable"


@pytest.mark.asyncio
async def test_upstream_error_never_leaks_the_key_to_client_or_log(
    async_client, opencode_go_enabled, fake_opencode_go
):
    secret = "sk-go-test-key"
    fake_opencode_go.chat_error = OpenCodeGoSidecarError(
        400,
        f"Invalid credential {secret}",
        body={"error": {"message": f"Invalid credential {secret}"}},
    )
    await _settings_payload(async_client)
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("go-key")

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}", "user-agent": "opencode/1.0"},
        json={"model": "opencode-go/glm-5.3", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert secret not in response.text
    logs = await _go_logs()
    assert logs
    assert secret not in (logs[0].error_message or "")


# --------------------------------------------------------------------------
# Dashboard endpoints
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_endpoint_records_health_and_counts_only_supported_models(
    async_client, monkeypatch, fake_opencode_go
):
    monkeypatch.setattr(
        "app.modules.opencode_go_sidecar.service.get_opencode_go_sidecar_client",
        lambda _config: fake_opencode_go,
    )
    await _settings_payload(async_client)

    response = await async_client.post("/api/opencode-go-sidecar/test")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    # Two of the five fake models are on /chat/completions. Reporting five would
    # tell an operator models are available that this build cannot route.
    assert body["modelCount"] == 2
    assert (await async_client.get("/api/settings")).json()["opencodeGoSidecarLastModelCount"] == 2


@pytest.mark.asyncio
async def test_test_endpoint_reports_unauthorized_without_leaking_the_key(
    async_client, monkeypatch, fake_opencode_go
):
    secret = "sk-go-test-key"

    async def _raise():
        raise OpenCodeGoSidecarError(401, f"Missing API key. got {secret}", body={})

    async def _list_models():
        return await _raise()

    fake_opencode_go.list_models = _list_models  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.modules.opencode_go_sidecar.service.get_opencode_go_sidecar_client",
        lambda _config: fake_opencode_go,
    )
    await _settings_payload(async_client)

    response = await async_client.post("/api/opencode-go-sidecar/test")

    assert response.json()["status"] == "unauthorized"
    assert secret not in response.text


@pytest.mark.asyncio
async def test_accounts_page_shows_a_read_only_go_card_without_fake_oauth_usage(
    async_client, opencode_go_enabled
):
    await _settings_payload(async_client)

    response = await async_client.get("/api/accounts")

    assert response.status_code == 200
    accounts = response.json()["accounts"]
    card = next(a for a in accounts if a["accountId"] == "opencode-go-sidecar")
    assert card["provider"] == "opencode_go"
    assert card["displayName"] == "OpenCode Go"
    assert card["readOnly"] is True
    assert card["synthetic"] is True
    # A $10/month API subscription is not a ChatGPT OAuth account; ``usage``
    # models the latter's rate-limit windows and must stay empty here.
    assert card["usage"] is None


# --------------------------------------------------------------------------
# Non-regression for existing providers
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_other_integrations_keep_their_routes(async_client, opencode_go_enabled, fake_opencode_go):
    await _settings_payload(async_client)

    response = await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "sk-orca-key",
            "orcarouterSidecarModelPrefixes": ["orcarouter/"],
        },
    )

    assert response.status_code == 200
    body = (await async_client.get("/api/settings")).json()
    # Enabling OpenCode Go must not disturb any existing integration.
    assert body["orcarouterSidecarEnabled"] is True
    assert body["orcarouterSidecarModelPrefixes"] == [{"prefix": "orcarouter/", "strip": False}]
    assert body["opencodeGoSidecarEnabled"] is True
