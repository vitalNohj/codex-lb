from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.auth.dependencies import (
    require_dashboard_write_access,
    set_dashboard_error_format,
    validate_dashboard_session,
)
from app.core.exceptions import DashboardBadRequestError
from app.dependencies import CliproxyAccountsContext, get_cliproxy_accounts_context
from app.modules.cliproxy_accounts.api_keys import normalize_api_key_write
from app.modules.cliproxy_accounts.providers import panel_oauth_providers
from app.modules.cliproxy_accounts.schemas import (
    CliproxyAccountsResponse,
    CliproxyApiKeyAccount,
    CliproxyApiKeyDeleteRequest,
    CliproxyApiKeyDeleteResponse,
    CliproxyApiKeyWriteRequest,
    CliproxyCatalogModelRequest,
    CliproxyCatalogModelResponse,
    CliproxyCredentialDeleteRequest,
    CliproxyCredentialDeleteResponse,
    CliproxyCredentialFieldsResponse,
    CliproxyCredentialFieldsUpdate,
    CliproxyCredentialRefreshResponse,
    CliproxyCredentialStatusResponse,
    CliproxyCredentialStatusUpdate,
    CliproxyCredentialUploadRequest,
    CliproxyCredentialUploadResponse,
    CliproxyOauthCallbackRequest,
    CliproxyOauthCallbackResponse,
    CliproxyOauthCancelResponse,
    CliproxyOauthProviderOption,
    CliproxyOauthProvidersResponse,
    CliproxyOauthStartResponse,
    CliproxyOauthStatusResponse,
)
from app.modules.cliproxy_accounts.validation import (
    CredentialFieldChange,
    validate_excluded_models,
    validate_priority,
    validate_weight,
)

router = APIRouter(
    prefix="/api/cliproxy",
    tags=["dashboard"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


@router.get("/accounts", response_model=CliproxyAccountsResponse)
async def list_cliproxy_accounts(
    provider: str | None = Query(default=None),
    context: CliproxyAccountsContext = Depends(get_cliproxy_accounts_context),
) -> CliproxyAccountsResponse:
    """List CLIProxyAPI credentials. Does not change dispatch."""

    normalized = provider.strip().lower() if provider and provider.strip() else None
    return await context.service.list_credentials(provider=normalized)


@router.patch("/accounts/{name}/fields", response_model=CliproxyCredentialFieldsResponse)
async def update_cliproxy_credential_fields(
    name: str,
    body: CliproxyCredentialFieldsUpdate,
    _write_access=Depends(require_dashboard_write_access),
    context: CliproxyAccountsContext = Depends(get_cliproxy_accounts_context),
) -> CliproxyCredentialFieldsResponse:
    """Update weight, priority, or excluded models for one credential."""

    change = _field_change(body)
    if change.is_empty():
        raise DashboardBadRequestError("No credential fields to update")
    return await context.service.update_fields(name, change)


@router.patch("/accounts/{name}/status", response_model=CliproxyCredentialStatusResponse)
async def update_cliproxy_credential_status(
    name: str,
    body: CliproxyCredentialStatusUpdate,
    _write_access=Depends(require_dashboard_write_access),
    context: CliproxyAccountsContext = Depends(get_cliproxy_accounts_context),
) -> CliproxyCredentialStatusResponse:
    """Enable or disable one credential.

    Disabling the last enabled account requires ``confirm``. Every other
    status change applies immediately.
    """

    return await context.service.set_credential_disabled(
        name,
        disabled=body.disabled,
        confirm=body.confirm,
    )


@router.get("/oauth/providers", response_model=CliproxyOauthProvidersResponse)
async def list_cliproxy_oauth_providers() -> CliproxyOauthProvidersResponse:
    """Providers the sign-in dialog can start. xAI is one of them and allows many accounts."""

    return CliproxyOauthProvidersResponse(
        providers=[
            CliproxyOauthProviderOption(provider=provider.panel, method=provider.method)
            for provider in panel_oauth_providers()
        ]
    )


@router.post("/oauth/{provider}/authorize", response_model=CliproxyOauthStartResponse)
async def start_cliproxy_oauth(
    provider: str,
    _write_access=Depends(require_dashboard_write_access),
    context: CliproxyAccountsContext = Depends(get_cliproxy_accounts_context),
) -> CliproxyOauthStartResponse:
    """Start a CLIProxyAPI sign-in. Each call adds an account; it does not replace one."""

    return await context.service.start_oauth(provider)


@router.get("/oauth/status", response_model=CliproxyOauthStatusResponse)
async def cliproxy_oauth_status(
    state: str = Query(),
    context: CliproxyAccountsContext = Depends(get_cliproxy_accounts_context),
) -> CliproxyOauthStatusResponse:
    return await context.service.oauth_status(state)


@router.delete("/oauth/session", response_model=CliproxyOauthCancelResponse)
async def cancel_cliproxy_oauth(
    state: str = Query(),
    _write_access=Depends(require_dashboard_write_access),
    context: CliproxyAccountsContext = Depends(get_cliproxy_accounts_context),
) -> CliproxyOauthCancelResponse:
    return await context.service.cancel_oauth(state)


@router.post("/oauth/callback", response_model=CliproxyOauthCallbackResponse)
async def submit_cliproxy_oauth_callback(
    body: CliproxyOauthCallbackRequest,
    _write_access=Depends(require_dashboard_write_access),
    context: CliproxyAccountsContext = Depends(get_cliproxy_accounts_context),
) -> CliproxyOauthCallbackResponse:
    """Store a pasted browser callback. The credential appears only after status is success."""

    return await context.service.submit_oauth_callback(
        provider_slug=body.provider,
        state=body.state,
        callback_url=body.callback_url,
    )


@router.post("/accounts/{name}/refresh", response_model=CliproxyCredentialRefreshResponse)
async def start_cliproxy_credential_refresh(
    name: str,
    _write_access=Depends(require_dashboard_write_access),
    context: CliproxyAccountsContext = Depends(get_cliproxy_accounts_context),
) -> CliproxyCredentialRefreshResponse:
    return await context.service.start_refresh(name)


@router.get("/accounts/{name}/refresh", response_model=CliproxyCredentialRefreshResponse)
async def cliproxy_credential_refresh_status(
    name: str,
    context: CliproxyAccountsContext = Depends(get_cliproxy_accounts_context),
) -> CliproxyCredentialRefreshResponse:
    return await context.service.refresh_status(name)


@router.delete("/accounts/{name}", response_model=CliproxyCredentialDeleteResponse)
async def delete_cliproxy_credential(
    name: str,
    body: CliproxyCredentialDeleteRequest,
    _write_access=Depends(require_dashboard_write_access),
    context: CliproxyAccountsContext = Depends(get_cliproxy_accounts_context),
) -> CliproxyCredentialDeleteResponse:
    """Turn the credential off, then delete it. One confirmation, one audit entry."""

    if not body.confirm:
        raise DashboardBadRequestError("Confirm before deleting this credential")
    return await context.service.delete_credential(name)


@router.post("/accounts/upload", response_model=CliproxyCredentialUploadResponse)
async def upload_cliproxy_credential(
    body: CliproxyCredentialUploadRequest,
    _write_access=Depends(require_dashboard_write_access),
    context: CliproxyAccountsContext = Depends(get_cliproxy_accounts_context),
) -> CliproxyCredentialUploadResponse:
    """Upload a credential file. A prefix already in the file is forwarded unchanged."""

    return await context.service.upload_credential(body.name, body.document)


@router.post("/api-keys", response_model=CliproxyApiKeyAccount)
async def create_cliproxy_api_key(
    body: CliproxyApiKeyWriteRequest,
    _write_access=Depends(require_dashboard_write_access),
    context: CliproxyAccountsContext = Depends(get_cliproxy_accounts_context),
) -> CliproxyApiKeyAccount:
    """Add one API-key provider entry through CLIProxyAPI's management list."""

    write = normalize_api_key_write(
        kind=body.kind,
        name=body.name,
        base_url=body.base_url,
        api_key=body.api_key,
        models=body.models,
        disabled=body.disabled,
        update_models=True,
        update_disabled="disabled" in body.model_fields_set,
        creating=True,
    )
    return await context.service.create_api_key(write)


@router.patch("/api-keys/{kind}/{index}", response_model=CliproxyApiKeyAccount)
async def update_cliproxy_api_key(
    kind: str,
    index: int,
    body: CliproxyApiKeyWriteRequest,
    _write_access=Depends(require_dashboard_write_access),
    context: CliproxyAccountsContext = Depends(get_cliproxy_accounts_context),
) -> CliproxyApiKeyAccount:
    """Edit one API-key entry. Omitted models and the on/off flag stay as stored."""

    if body.kind != kind:
        raise DashboardBadRequestError("API-key provider does not match the account")
    provided = body.model_fields_set
    write = normalize_api_key_write(
        kind=kind,
        name=body.name,
        base_url=body.base_url,
        api_key=body.api_key,
        models=body.models,
        disabled=body.disabled,
        update_models="models" in provided,
        update_disabled="disabled" in provided,
        creating=False,
    )
    return await context.service.update_api_key(index, write)


@router.delete("/api-keys/{kind}/{index}", response_model=CliproxyApiKeyDeleteResponse)
async def delete_cliproxy_api_key(
    kind: str,
    index: int,
    body: CliproxyApiKeyDeleteRequest,
    _write_access=Depends(require_dashboard_write_access),
    context: CliproxyAccountsContext = Depends(get_cliproxy_accounts_context),
) -> CliproxyApiKeyDeleteResponse:
    if not body.confirm:
        raise DashboardBadRequestError("Confirm before removing this API-key account")
    await context.service.delete_api_key(kind, index)
    return CliproxyApiKeyDeleteResponse(kind=kind, index=index, deleted=True)


@router.post("/catalog/models", response_model=CliproxyCatalogModelResponse)
async def add_cliproxy_catalog_model(
    body: CliproxyCatalogModelRequest,
    _write_access=Depends(require_dashboard_write_access),
    context: CliproxyAccountsContext = Depends(get_cliproxy_accounts_context),
) -> CliproxyCatalogModelResponse:
    """Add one discovered model id to the existing CLIProxyAPI model list."""

    return await context.service.add_catalog_model(body.model)


def _field_change(body: CliproxyCredentialFieldsUpdate) -> CredentialFieldChange:
    provided = body.model_fields_set
    weight = validate_weight(body.weight) if "weight" in provided and body.weight is not None else None
    priority = validate_priority(body.priority) if "priority" in provided and body.priority is not None else None
    excluded: tuple[str, ...] | None = None
    if "excluded_models" in provided:
        if body.excluded_models is None:
            raise DashboardBadRequestError("Excluded models must be a list")
        excluded = validate_excluded_models(body.excluded_models)
    return CredentialFieldChange(
        weight=weight,
        priority=priority,
        excluded_models=excluded,
        update_weight="weight" in provided,
        update_priority="priority" in provided,
        update_excluded_models="excluded_models" in provided,
    )
