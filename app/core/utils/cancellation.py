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

__all__ = ["await_cleanup_deferring_cancellation", "await_result_deferring_cancellation"]

_T = TypeVar("_T")


async def await_result_deferring_cancellation(awaitable: Awaitable[_T]) -> tuple[_T, bool]:
    """Run ``awaitable`` to completion, deferring cancellation until it finishes.

    Returns ``(result, cancellation_deferred)``. A cancellation delivered while
    the awaitable is in flight is absorbed so the cleanup can finish, and
    reported through the flag so the caller can re-raise it - deferred, never
    swallowed. If the awaitable is itself cancelled, that propagates at once.

    The flag is returned rather than re-raised here so a caller that still has
    its own required cleanup to run can finish it first, which is exactly how
    the long-standing ``_await_result_deferring_cancellation`` in
    ``app/modules/proxy/api.py`` is used. Callers that have nothing further to
    do should use :func:`await_cleanup_deferring_cancellation`.

    This bounds nothing on its own: callers must pass work that already
    terminates (an owned settlement or cleanup), never an open-ended wait.
    Ordinary failures propagate unchanged - nothing is suppressed here.
    """

    task = asyncio.ensure_future(awaitable)
    cancellation_deferred = False
    with anyio.CancelScope(shield=True):
        while True:
            try:
                return await asyncio.shield(task), cancellation_deferred
            except asyncio.CancelledError:
                if task.cancelled():
                    raise
                cancellation_deferred = True
    raise RuntimeError("unreachable shielded cancellation-deferral state")


async def await_cleanup_deferring_cancellation(awaitable: Awaitable[_T]) -> _T:
    """Finish ``awaitable``, then re-raise any cancellation that arrived meanwhile.

    For callers whose only remaining obligation is this cleanup: the cleanup
    completes, and a caller cancellation that arrived during it is re-delivered
    so the request still terminates as cancelled.
    """

    result, cancellation_deferred = await await_result_deferring_cancellation(awaitable)
    if cancellation_deferred:
        raise asyncio.CancelledError
    return result
