"""In-process refresh status the panel polls while CLIProxyAPI refreshes a credential.

The upstream refresh call is one HTTP request. The panel still sees pending,
then ok or error, because that request can outlive the click that started it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from app.modules.cliproxy_accounts.redaction import public_message

logger = logging.getLogger(__name__)

RefreshStatus = Literal["pending", "ok", "error"]
RefreshCallback = Callable[[RefreshStatus, str | None], None]


@dataclass(frozen=True, slots=True)
class RefreshObservation:
    name: str
    status: RefreshStatus
    message: str | None = None


_jobs: dict[str, RefreshObservation] = {}
_tasks: dict[str, asyncio.Task[None]] = {}
_lock = asyncio.Lock()


async def begin_refresh(
    name: str,
    runner: Callable[[], Awaitable[None]],
    on_done: RefreshCallback,
) -> RefreshObservation:
    async with _lock:
        current = _jobs.get(name)
        task = _tasks.get(name)
        if current is not None and current.status == "pending" and task is not None and not task.done():
            return current
        pending = RefreshObservation(name=name, status="pending")
        _jobs[name] = pending
        started = asyncio.create_task(_execute(name, runner, on_done), name=f"cliproxy-refresh-{name}")
        started.add_done_callback(_consume_task_result)
        _tasks[name] = started
        return pending


def current_refresh(name: str) -> RefreshObservation | None:
    return _jobs.get(name)


async def reset_refresh_jobs() -> None:
    async with _lock:
        tasks = list(_tasks.values())
        _tasks.clear()
        _jobs.clear()
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except (asyncio.CancelledError, Exception):
            logger.debug("CLIProxyAPI refresh task ended during reset", exc_info=True)


async def _execute(name: str, runner: Callable[[], Awaitable[None]], on_done: RefreshCallback) -> None:
    try:
        await runner()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        message = public_message(getattr(exc, "message", None) or str(exc) or "Refresh failed")
        _jobs[name] = RefreshObservation(name=name, status="error", message=message or "Refresh failed")
        _notify(on_done, "error", _jobs[name].message)
        return
    _jobs[name] = RefreshObservation(name=name, status="ok")
    _notify(on_done, "ok", None)


def _notify(on_done: RefreshCallback, status: RefreshStatus, message: str | None) -> None:
    try:
        on_done(status, message)
    except Exception:
        logger.warning("CLIProxyAPI refresh callback failed", exc_info=True)


def _consume_task_result(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except (asyncio.CancelledError, Exception):
        return
