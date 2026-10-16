"""Dashboard routes for the CLIProxyAPI config file.

``GET`` returns the redacted document. ``POST /preview`` is the dry-run diff.
``PUT`` writes only when ``confirm`` is true. ``POST /rollback`` restores the
snapshot kept in codex-lb. Routing flags use ``PATCH /config/routing/<field>``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.core.auth.dependencies import (
    require_dashboard_write_access,
    set_dashboard_error_format,
    validate_dashboard_session,
)
from app.core.errors import dashboard_error
from app.dependencies import CliproxyConfigContext, get_cliproxy_config_context
from app.modules.cliproxy_accounts.config_schemas import (
    CliproxyConfigDocumentRequest,
    CliproxyConfigPreview,
    CliproxyConfigReplaceRequest,
    CliproxyConfigRollbackRequest,
    CliproxyConfigRoutingFlagUpdate,
    CliproxyConfigView,
)
from app.modules.cliproxy_accounts.config_service import CliproxyConfigOperationError

router = APIRouter(
    prefix="/api/cliproxy",
    tags=["dashboard"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


def _actor_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _failure(exc: CliproxyConfigOperationError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=dashboard_error(exc.code, exc.message))


@router.get("/config", response_model=CliproxyConfigView)
async def get_config(context: CliproxyConfigContext = Depends(get_cliproxy_config_context)) -> CliproxyConfigView:
    return await context.service.view()


@router.post("/config/preview", response_model=CliproxyConfigPreview)
async def preview_config(
    body: CliproxyConfigDocumentRequest,
    _write_access: object = Depends(require_dashboard_write_access),
    context: CliproxyConfigContext = Depends(get_cliproxy_config_context),
) -> CliproxyConfigPreview | JSONResponse:
    try:
        return await context.service.preview(body.yaml, body.content_sha256)
    except CliproxyConfigOperationError as exc:
        return _failure(exc)


@router.put("/config", response_model=CliproxyConfigView)
async def replace_config(
    body: CliproxyConfigReplaceRequest,
    request: Request,
    _write_access: object = Depends(require_dashboard_write_access),
    context: CliproxyConfigContext = Depends(get_cliproxy_config_context),
) -> CliproxyConfigView | JSONResponse:
    try:
        return await context.service.replace(body.yaml, body.content_sha256, actor_ip=_actor_ip(request))
    except CliproxyConfigOperationError as exc:
        return _failure(exc)


@router.post("/config/rollback", response_model=CliproxyConfigView)
async def rollback_config(
    body: CliproxyConfigRollbackRequest,
    request: Request,
    _write_access: object = Depends(require_dashboard_write_access),
    context: CliproxyConfigContext = Depends(get_cliproxy_config_context),
) -> CliproxyConfigView | JSONResponse:
    del body
    try:
        return await context.service.rollback(actor_ip=_actor_ip(request))
    except CliproxyConfigOperationError as exc:
        return _failure(exc)


@router.patch("/config/routing/{field}", response_model=CliproxyConfigView)
async def patch_routing_flag(
    field: str,
    body: CliproxyConfigRoutingFlagUpdate,
    request: Request,
    _write_access: object = Depends(require_dashboard_write_access),
    context: CliproxyConfigContext = Depends(get_cliproxy_config_context),
) -> CliproxyConfigView | JSONResponse:
    try:
        return await context.service.patch_routing_flag(
            field,
            body.enabled,
            body.content_sha256,
            actor_ip=_actor_ip(request),
        )
    except CliproxyConfigOperationError as exc:
        return _failure(exc)
