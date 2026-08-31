from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth.dependencies import set_dashboard_error_format, validate_dashboard_session
from app.core.config.product_capabilities import omniroute_enabled
from app.modules.runtime.schemas import RuntimeCapabilitiesResponse, RuntimeVersionResponse
from app.modules.runtime.service import get_runtime_version_service

router = APIRouter(
    prefix="/api/runtime",
    tags=["runtime"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


@router.get("/version", response_model=RuntimeVersionResponse)
async def get_runtime_version() -> RuntimeVersionResponse:
    return await get_runtime_version_service().get_version_status()


@router.get("/capabilities", response_model=RuntimeCapabilitiesResponse)
async def get_runtime_capabilities() -> RuntimeCapabilitiesResponse:
    return RuntimeCapabilitiesResponse(omniroute=omniroute_enabled())
