from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app.core.auth.dashboard_access import DashboardPrincipal, DashboardRole, admin_principal
from app.core.auth.dashboard_mode import DashboardAuthMode, get_dashboard_request_auth
from app.core.auth.dependencies import (
    record_authenticated_api_key,
    set_openai_error_format,
    validate_dashboard_session,
    validate_required_proxy_api_key_authorization,
)
from app.core.exceptions import DashboardAuthError, ProxyAuthError
from app.dependencies import QuotaFeedContext, get_quota_feed_context
from app.modules.dashboard_auth.service import DASHBOARD_SESSION_COOKIE, get_dashboard_session_store
from app.modules.quota_feed.schemas import QuotaFeedResponse
from app.modules.quota_feed.service import QuotaFeedScope

QUOTA_FEED_CACHE_MAX_AGE_SECONDS = 15
QUOTA_FEED_CACHE_CONTROL = f"private, max-age={QUOTA_FEED_CACHE_MAX_AGE_SECONDS}"

router = APIRouter(
    prefix="/v1",
    tags=["quota-feed"],
    dependencies=[Depends(set_openai_error_format)],
)


async def require_quota_feed_caller(request: Request) -> QuotaFeedScope:
    """Accept a proxy API key or a real dashboard credential.

    A presented ``Authorization`` header is validated as a proxy API key and
    does not fall through to the dashboard session. Passwordless local
    dashboard access, dashboard auth mode ``disabled``, and guest sessions
    are not credentials: this route returns 401 unless the caller presents a
    key, a verified admin session cookie, or the trusted-header identity the
    dashboard already uses.
    """

    authorization = request.headers.get("authorization")
    if authorization is not None:
        api_key = await validate_required_proxy_api_key_authorization(authorization)
        record_authenticated_api_key(request, api_key)
        if api_key.account_assignment_scope_enabled:
            assigned = frozenset(account_id for account_id in api_key.assigned_account_ids if account_id)
            return QuotaFeedScope(codex_account_ids=assigned, include_sidecar=True)
        return QuotaFeedScope(codex_account_ids=None, include_sidecar=True)

    principal = await _dashboard_principal(request)
    if principal is None or principal.role != DashboardRole.ADMIN:
        raise ProxyAuthError("Authentication required")
    return QuotaFeedScope(codex_account_ids=None, include_sidecar=True)


async def _dashboard_principal(request: Request) -> DashboardPrincipal | None:
    request_auth = get_dashboard_request_auth(request)
    if request_auth is not None and request_auth.mode == DashboardAuthMode.TRUSTED_HEADER:
        return admin_principal(auth_mode=request_auth.mode, actor=request_auth.actor)

    session_id = request.cookies.get(DASHBOARD_SESSION_COOKIE)
    if not session_id or get_dashboard_session_store().get(session_id) is None:
        return None
    try:
        return await validate_dashboard_session(request)
    except DashboardAuthError as exc:
        raise ProxyAuthError("Authentication required") from exc


@router.get("/quota-feed", response_model=QuotaFeedResponse)
async def get_quota_feed(
    response: Response,
    scope: QuotaFeedScope = Depends(require_quota_feed_caller),
    context: QuotaFeedContext = Depends(get_quota_feed_context),
) -> QuotaFeedResponse:
    response.headers["Cache-Control"] = QUOTA_FEED_CACHE_CONTROL
    response.headers["Vary"] = "Authorization, Cookie"
    return await context.service.build(scope)
