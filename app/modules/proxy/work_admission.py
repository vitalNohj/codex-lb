from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.core.clients.proxy import ProxyResponseError
from app.core.resilience.overload import local_overload_error
from app.core.utils.request_id import get_request_id

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AdmissionLease:
    _semaphore: asyncio.Semaphore | None
    _released: bool = False

    def release(self) -> None:
        if self._released or self._semaphore is None:
            return
        self._released = True
        self._semaphore.release()


@dataclass(slots=True)
class _AdmissionGate:
    semaphore: asyncio.Semaphore
    lock: asyncio.Lock


class WorkAdmissionController:
    def __init__(
        self,
        *,
        token_refresh_limit: int,
        websocket_connect_limit: int,
        response_create_limit: int,
        compact_response_create_limit: int,
    ) -> None:
        self._token_refresh = _make_gate(token_refresh_limit)
        self._websocket_connect = _make_gate(websocket_connect_limit)
        self._response_create = _make_gate(response_create_limit)
        self._compact_response_create = _make_gate(compact_response_create_limit)

    async def acquire_token_refresh(self) -> AdmissionLease:
        return await self._acquire(self._token_refresh, stage="token_refresh")

    async def acquire_websocket_connect(self) -> AdmissionLease:
        return await self._acquire(self._websocket_connect, stage="upstream_websocket_connect")

    async def acquire_response_create(self, *, compact: bool = False) -> AdmissionLease:
        semaphore = self._compact_response_create if compact else self._response_create
        stage = "compact_response_create" if compact else "response_create"
        return await self._acquire(semaphore, stage=stage)

    async def _acquire(self, gate: _AdmissionGate | None, *, stage: str) -> AdmissionLease:
        if gate is None:
            return AdmissionLease(None)
        async with gate.lock:
            if gate.semaphore.locked():
                message = f"codex-lb is temporarily overloaded during {stage}"
                logger.warning(
                    "proxy_admission_rejected request_id=%s stage=%s status=429 available=%s message=%s",
                    get_request_id(),
                    stage,
                    0,
                    message,
                )
                raise ProxyResponseError(429, local_overload_error(message))
            await gate.semaphore.acquire()
        return AdmissionLease(gate.semaphore)


def _make_gate(limit: int) -> _AdmissionGate | None:
    if limit <= 0:
        return None
    return _AdmissionGate(semaphore=asyncio.Semaphore(limit), lock=asyncio.Lock())
