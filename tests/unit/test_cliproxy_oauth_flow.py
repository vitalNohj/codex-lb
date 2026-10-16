from __future__ import annotations

import pytest

from app.core.clients.claude_sidecar import (
    ClaudeSidecarClient,
    ClaudeSidecarConfig,
    ClaudeSidecarUnavailableError,
)
from app.core.exceptions import DashboardBadRequestError
from app.modules.cliproxy_accounts.management import CliproxyManagement
from app.modules.cliproxy_accounts.oauth_flow import project_callback, project_cancel, project_start, project_status
from app.modules.cliproxy_accounts.providers import oauth_provider
from app.modules.cliproxy_accounts.schemas import (
    CliproxyAccountsResponse,
    CliproxyCredentialDeleteResponse,
    CliproxyCredentialFieldsResponse,
    CliproxyCredentialRefreshResponse,
    CliproxyCredentialStatusResponse,
    CliproxyCredentialUploadResponse,
    CliproxyOauthCallbackResponse,
    CliproxyOauthCancelResponse,
    CliproxyOauthProvidersResponse,
    CliproxyOauthStartResponse,
    CliproxyOauthStatusResponse,
)
from app.modules.cliproxy_accounts.upload import prepare_upload_document

_TOKEN_FIELDS = frozenset(
    {
        "access_token",
        "accessToken",
        "refresh_token",
        "refreshToken",
        "id_token",
        "idToken",
        "api_key",
        "apiKey",
        "client_secret",
        "clientSecret",
        "device_code",
        "deviceCode",
        "authorization",
        "password",
        "secret",
    }
)

_PANEL_RESPONSES = (
    CliproxyAccountsResponse,
    CliproxyCredentialFieldsResponse,
    CliproxyCredentialStatusResponse,
    CliproxyOauthProvidersResponse,
    CliproxyOauthStartResponse,
    CliproxyOauthStatusResponse,
    CliproxyOauthCancelResponse,
    CliproxyOauthCallbackResponse,
    CliproxyCredentialRefreshResponse,
    CliproxyCredentialDeleteResponse,
    CliproxyCredentialUploadResponse,
)


def _property_names(node: object) -> set[str]:
    names: set[str] = set()
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            names.update(str(key) for key in properties)
        for value in node.values():
            names.update(_property_names(value))
    elif isinstance(node, list):
        for item in node:
            names.update(_property_names(item))
    return names


def test_panel_response_schemas_have_no_token_fields():
    leaked = {
        model.__name__: sorted(_property_names(model.model_json_schema()) & _TOKEN_FIELDS) for model in _PANEL_RESPONSES
    }
    assert leaked == {model.__name__: [] for model in _PANEL_RESPONSES}


def test_oauth_projection_drops_tokens_and_maps_pending_ok_error_cancel():
    provider = oauth_provider("xai")
    assert provider is not None
    started = project_start(
        provider,
        {
            "url": "https://auth.example/device",
            "state": "xai-1",
            "flow": "device",
            "user_code": "ABCD-1234",
            "expires_in": 30,
            "access_token": "cliproxy-test-access-token",
        },
    )
    dumped = started.model_dump()
    assert dumped["method"] == "device"
    assert dumped["verification_url"] == "https://auth.example/device"
    assert "access_token" not in dumped
    assert project_status({"status": "wait", "access_token": "cliproxy-test-access-token"}).status == "pending"
    assert project_status({"status": "ok", "refresh_token": "cliproxy-test-refresh-token"}).status == "success"
    failed = project_status({"status": "error", "error": "code=super-secret-auth-code"})
    assert failed.status == "error"
    assert failed.error_message is not None
    assert "super-secret-auth-code" not in failed.error_message
    assert project_cancel({"cancelled": True, "access_token": "cliproxy-test-access-token"}).cancelled is True
    callback = project_callback({"status": "ok", "access_token": "cliproxy-test-access-token"})
    assert callback.status == "pending"
    assert "access_token" not in callback.model_dump()


@pytest.mark.asyncio
async def test_management_refuses_a_missing_key_before_any_request(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("management call reached the network")

    monkeypatch.setattr("app.modules.cliproxy_accounts.management.lease_http_session", explode)
    client_config = ClaudeSidecarConfig(
        enabled=False,
        base_url="http://127.0.0.1:9",
        api_key=None,
        prefixes=(),
        connect_timeout_seconds=1,
        request_timeout_seconds=1,
        models_cache_ttl_seconds=1,
        management_key="  ",
    )
    with pytest.raises(ClaudeSidecarUnavailableError, match="not configured"):
        await CliproxyManagement(ClaudeSidecarClient(client_config)).start_oauth("/v0/management/xai-auth-url")


def test_upload_rejects_fields_the_panel_cannot_validate_and_strips_prefix():
    with pytest.raises(DashboardBadRequestError, match="mystery"):
        prepare_upload_document('{"type":"xai","access_token":"secret","mystery":true}')

    prepared = prepare_upload_document('{"type":"xai","access_token":"secret","prefix":"acct8"}')
    assert prepared.prefix == "acct8"
    assert b"prefix" not in prepared.body
    assert b"secret" in prepared.body
