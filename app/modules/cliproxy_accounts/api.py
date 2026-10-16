from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.auth.dependencies import set_dashboard_error_format, validate_dashboard_session
from app.core.exceptions import DashboardBadRequestError
from app.dependencies import CliproxyAccountsContext, get_cliproxy_accounts_context
from app.modules.cliproxy_accounts.schemas import (
    CliproxyAccountsResponse,
    CliproxyCredentialFieldsResponse,
    CliproxyCredentialFieldsUpdate,
    CliproxyCredentialStatusResponse,
    CliproxyCredentialStatusUpdate,
)
from app.modules.cliproxy_accounts.validation import (
    CredentialFieldChange,
    normalize_credential_prefix,
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
    context: CliproxyAccountsContext = Depends(get_cliproxy_accounts_context),
) -> CliproxyCredentialFieldsResponse:
    """Update prefix, weight, priority, or excluded models for one credential."""

    change = _field_change(body)
    if change.is_empty():
        raise DashboardBadRequestError("No credential fields to update")
    return await context.service.update_fields(name, change)


@router.patch("/accounts/{name}/status", response_model=CliproxyCredentialStatusResponse)
async def update_cliproxy_credential_status(
    name: str,
    body: CliproxyCredentialStatusUpdate,
    context: CliproxyAccountsContext = Depends(get_cliproxy_accounts_context),
) -> CliproxyCredentialStatusResponse:
    """Enable or disable one credential after the panel confirms it.

    ``CliproxyAccountsService.set_credential_disabled`` is the reusable write.
    This route refuses the call until ``confirm`` is true so a click cannot
    change the credential by itself.
    """

    if not body.confirm:
        raise DashboardBadRequestError("Confirm before enabling or disabling this credential")
    return await context.service.set_credential_disabled(name, disabled=body.disabled)


def _field_change(body: CliproxyCredentialFieldsUpdate) -> CredentialFieldChange:
    provided = body.model_fields_set
    prefix: str | None = None
    if "prefix" in provided and body.prefix is not None and body.prefix.strip():
        prefix = normalize_credential_prefix(body.prefix)
    weight = validate_weight(body.weight) if "weight" in provided and body.weight is not None else None
    priority = validate_priority(body.priority) if "priority" in provided and body.priority is not None else None
    excluded: tuple[str, ...] | None = None
    if "excluded_models" in provided:
        if body.excluded_models is None:
            raise DashboardBadRequestError("Excluded models must be a list")
        excluded = validate_excluded_models(body.excluded_models)
    return CredentialFieldChange(
        prefix=prefix,
        weight=weight,
        priority=priority,
        excluded_models=excluded,
        update_prefix="prefix" in provided,
        update_weight="weight" in provided,
        update_priority="priority" in provided,
        update_excluded_models="excluded_models" in provided,
    )
