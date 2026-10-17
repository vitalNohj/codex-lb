from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.modules.claude_sidecar.excluded_models import ExcludedModelsState
from app.modules.shared.schemas import DashboardModel

CliproxyAccountsStatus = Literal["healthy", "not_configured", "unauthorized", "unreachable", "error"]


class CliproxyQuotaWindow(DashboardModel):
    """One Grok consumer window for a credential card."""

    id: str
    label: str
    kind: str
    percent_remaining: float
    resets_at: datetime | None = None


class CliproxyCredential(DashboardModel):
    """One CLIProxyAPI credential. Token fields are never part of this contract."""

    name: str
    auth_index: str | None = None
    email: str | None = None
    provider: str
    health: str
    disabled: bool = False
    unavailable: bool = False
    quota_exceeded: bool = False
    # Read from the auth file when CLIProxyAPI returns one. The panel does
    # not assign or rewrite it.
    prefix: str | None = None
    weight: int | None = None
    priority: int | None = None
    excluded_models: list[str] = Field(default_factory=list)
    excluded_models_state: ExcludedModelsState = "unreadable"
    models: list[str] = Field(default_factory=list)
    models_error: str | None = None
    quota_windows: list[CliproxyQuotaWindow] = Field(default_factory=list)
    prepaid_credits: int | None = None
    usage_tokens: int | None = None
    usage_requests: int | None = None


class CliproxyProviderCredentials(DashboardModel):
    provider: str
    credentials: list[CliproxyCredential] = Field(default_factory=list)


class CliproxyApiKeyModel(DashboardModel):
    name: str
    alias: str


class CliproxyApiKeyAccount(DashboardModel):
    """One API-key provider entry. The key itself is never included."""

    id: str
    kind: str
    index: int
    name: str
    base_url: str
    disabled: bool | None = None
    supports_disable: bool
    has_api_key: bool
    models: list[CliproxyApiKeyModel] = Field(default_factory=list)
    discovered_models: list[str] = Field(default_factory=list)
    models_error: str | None = None
    auth_index: str | None = None
    prefix: str | None = None


class CliproxyAccountsResponse(DashboardModel):
    status: CliproxyAccountsStatus
    message: str | None = None
    providers: list[CliproxyProviderCredentials] = Field(default_factory=list)
    api_keys: list[CliproxyApiKeyAccount] = Field(default_factory=list)
    api_keys_message: str | None = None
    shared_model_ids: list[str] = Field(default_factory=list)


class CliproxyCredentialFieldsUpdate(DashboardModel):
    weight: int | None = None
    priority: int | None = None
    excluded_models: list[str] | None = None


class CliproxyCredentialFieldsResponse(DashboardModel):
    name: str
    prefix: str | None = None
    weight: int | None = None
    priority: int | None = None
    excluded_models: list[str] = Field(default_factory=list)
    excluded_models_state: ExcludedModelsState = "unreadable"
    disabled: bool = False


class CliproxyCredentialStatusUpdate(DashboardModel):
    disabled: bool
    confirm: bool = False


class CliproxyCredentialStatusResponse(DashboardModel):
    name: str
    disabled: bool


CliproxyOauthMethod = Literal["browser", "device"]
CliproxyOauthStatus = Literal["pending", "success", "error"]
CliproxyRefreshStatus = Literal["pending", "ok", "error"]


class CliproxyOauthProviderOption(DashboardModel):
    provider: str
    method: CliproxyOauthMethod


class CliproxyOauthProvidersResponse(DashboardModel):
    providers: list[CliproxyOauthProviderOption] = Field(default_factory=list)


class CliproxyOauthStartResponse(DashboardModel):
    state: str
    provider: str
    method: CliproxyOauthMethod
    authorization_url: str | None = None
    verification_url: str | None = None
    user_code: str | None = None
    interval_seconds: int
    expires_in_seconds: int | None = None


class CliproxyOauthStatusResponse(DashboardModel):
    status: CliproxyOauthStatus
    error_message: str | None = None


class CliproxyOauthCancelResponse(DashboardModel):
    status: Literal["ok"]
    cancelled: bool


class CliproxyOauthCallbackRequest(DashboardModel):
    provider: str
    state: str
    callback_url: str


class CliproxyOauthCallbackResponse(DashboardModel):
    status: CliproxyOauthStatus
    error_message: str | None = None


class CliproxyCredentialRefreshResponse(DashboardModel):
    name: str
    status: CliproxyRefreshStatus
    message: str | None = None


class CliproxyCredentialDeleteRequest(DashboardModel):
    confirm: bool


class CliproxyCredentialDeleteResponse(DashboardModel):
    name: str
    disabled: bool
    deleted: bool


class CliproxyCredentialUploadRequest(DashboardModel):
    name: str
    document: str


class CliproxyCredentialUploadResponse(DashboardModel):
    name: str
    provider: str
    prefix: str | None = None


class CliproxyApiKeyWriteRequest(DashboardModel):
    kind: str
    name: str | None = None
    base_url: str
    api_key: str | None = None
    models: list[str] = Field(default_factory=list)
    disabled: bool | None = None
    account_id: str | None = None


class CliproxyApiKeyDeleteRequest(DashboardModel):
    confirm: bool
    account_id: str


class CliproxyApiKeyDeleteResponse(DashboardModel):
    kind: str
    index: int
    deleted: bool


class CliproxyCatalogModelRequest(DashboardModel):
    model: str


class CliproxyCatalogModelResponse(DashboardModel):
    model: str
    full_models: list[str] = Field(default_factory=list)
