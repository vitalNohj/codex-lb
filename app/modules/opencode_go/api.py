"""Dashboard route for the OpenCode Go subscription quota.

One read-only endpoint behind the dashboard's existing session auth - the same
dependencies as ``/api/claude-sidecar/quota``. No new auth scheme and no
unauthenticated variant: the response is derived from a subscription credential
and is operator data.

The route deliberately does not appear in health or status checks. A health
probe that reached upstream would be a hidden inference-adjacent call against a
metered subscription, and would let an upstream outage mark codex-lb unhealthy.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth.dependencies import set_dashboard_error_format, validate_dashboard_session
from app.dependencies import OpenCodeGoContext, get_opencode_go_context
from app.modules.opencode_go.schemas import OpenCodeGoQuotaResponse

router = APIRouter(
    prefix="/api/opencode-go",
    tags=["dashboard"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


@router.get("/quota", response_model=OpenCodeGoQuotaResponse)
async def get_quota(
    context: OpenCodeGoContext = Depends(get_opencode_go_context),
) -> OpenCodeGoQuotaResponse:
    """Current OpenCode Go usage windows.

    Always HTTP 200: every upstream failure is carried in ``status`` so the
    dashboard can tell "unavailable" from "exhausted" instead of seeing a 502.
    """
    return await context.service.get_quota()
