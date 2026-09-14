from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth.dependencies import set_dashboard_error_format, validate_dashboard_session
from app.dependencies import FreeModelDiscoveryContext, get_free_model_discovery_context
from app.core.exceptions import DashboardConflictError
from app.modules.free_model_discovery.runner import (
    discovery_execution_enabled,
    wake_free_model_discovery_runner,
)
from app.modules.free_model_discovery.schemas import (
    FreeModelDiscoveryPlanResponse,
    FreeModelDiscoveryRunResponse,
    FreeModelDiscoveryRunsResponse,
    FreeModelDiscoveryStartRequest,
)

router = APIRouter(
    prefix="/api/free-model-discovery",
    tags=["dashboard"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


@router.get("/plan", response_model=FreeModelDiscoveryPlanResponse)
async def get_plan(
    context: FreeModelDiscoveryContext = Depends(get_free_model_discovery_context),
) -> FreeModelDiscoveryPlanResponse:
    return await context.service.build_plan()


@router.post("/runs", response_model=FreeModelDiscoveryRunResponse, status_code=201)
async def start_run(
    payload: FreeModelDiscoveryStartRequest,
    context: FreeModelDiscoveryContext = Depends(get_free_model_discovery_context),
) -> FreeModelDiscoveryRunResponse:
    # Refuse before creating the row. Accepting a run nothing will drive leaves
    # a permanently ``running`` record which, under the single-active index,
    # blocks every later run. Checked here rather than in the service because
    # the runner module imports the service.
    if not discovery_execution_enabled():
        raise DashboardConflictError(
            "Free model discovery cannot start because background automations are disabled. "
            "Enable the automations scheduler and try again.",
            code="discovery_execution_disabled",
        )
    run = await context.service.start_run(payload)
    wake_free_model_discovery_runner()
    return run


@router.get("/runs", response_model=FreeModelDiscoveryRunsResponse)
async def list_runs(
    context: FreeModelDiscoveryContext = Depends(get_free_model_discovery_context),
) -> FreeModelDiscoveryRunsResponse:
    return await context.service.list_runs()


@router.get("/runs/current", response_model=FreeModelDiscoveryRunResponse | None)
async def get_current_run(
    context: FreeModelDiscoveryContext = Depends(get_free_model_discovery_context),
) -> FreeModelDiscoveryRunResponse | None:
    return await context.service.get_active_or_latest_run()


@router.get("/runs/{run_id}", response_model=FreeModelDiscoveryRunResponse)
async def get_run(
    run_id: str,
    context: FreeModelDiscoveryContext = Depends(get_free_model_discovery_context),
) -> FreeModelDiscoveryRunResponse:
    return await context.service.get_run(run_id)


@router.post("/runs/{run_id}/cancel", response_model=FreeModelDiscoveryRunResponse)
async def cancel_run(
    run_id: str,
    context: FreeModelDiscoveryContext = Depends(get_free_model_discovery_context),
) -> FreeModelDiscoveryRunResponse:
    return await context.service.cancel_run(run_id)
