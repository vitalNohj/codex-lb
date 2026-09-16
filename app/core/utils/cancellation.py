"""Finish a required cleanup despite cancellation being delivered to the caller.

Cleanup that writes durable accounting cannot simply run in a ``finally``: the
``finally`` executes, but the first ``await`` inside it re-raises the pending
``CancelledError``, so work after that point never happens. For a reservation
settlement that means the reservation is left held and the caller's quota stays
consumed.

The deferral shields the cleanup, absorbs cancellations that arrive while it is
running, and re-raises once it has finished - so the request still terminates as
cancelled, and cancellation is deferred rather than swallowed. This mirrors
``_await_result_deferring_cancellation`` in ``app/modules/proxy/api.py``, which
has long used the same pattern for owned proxy cleanup; it lives here so
non-proxy callers can share one implementation instead of copying it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

import anyio

__all__ = ["await_result_deferring_cancellation"]

_T = TypeVar("_T")


async def await_result_deferring_cancellation(awaitable: Awaitable[_T]) -> _T:
    """Run ``awaitable`` to completion and return its result, deferring cancellation.

    A cancellation delivered while the awaitable is in flight is absorbed and
    re-delivered after it completes. If the awaitable is itself cancelled, that
    cancellation propagates immediately.

    This bounds nothing on its own: callers must pass work that already
    terminates (an owned settlement or cleanup), never an open-ended wait.
    Ordinary failures propagate unchanged - nothing is suppressed here.
    """

    task = asyncio.ensure_future(awaitable)
    with anyio.CancelScope(shield=True):
        while True:
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                if task.cancelled():
                    raise
    raise RuntimeError("unreachable shielded cancellation-deferral state")
