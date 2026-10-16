from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.auth.dependencies import set_dashboard_error_format, validate_dashboard_session
from app.dependencies import CliproxyAccountsContext, get_cliproxy_accounts_context
from app.modules.cliproxy_accounts.schemas import CliproxyAccountsResponse

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
    """List CLIProxyAPI credentials. Read-only; does not change dispatch."""

    normalized = provider.strip().lower() if provider and provider.strip() else None
    return await context.service.list_credentials(provider=normalized)
