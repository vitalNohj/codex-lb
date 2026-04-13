from __future__ import annotations

import asyncio

import pytest

from app.core.clients.proxy import ProxyResponseError
from app.modules.proxy.work_admission import WorkAdmissionController

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_work_admission_rejects_concurrent_race_without_waiting() -> None:
    controller = WorkAdmissionController(
        token_refresh_limit=1,
        websocket_connect_limit=0,
        response_create_limit=0,
        compact_response_create_limit=0,
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        lease = await controller.acquire_token_refresh()
        started.set()
        try:
            await release.wait()
        finally:
            lease.release()

    first = asyncio.create_task(holder())
    await started.wait()

    with pytest.raises(ProxyResponseError) as exc_info:
        await asyncio.wait_for(controller.acquire_token_refresh(), timeout=0.1)

    release.set()
    await first

    assert exc_info.value.status_code == 429
