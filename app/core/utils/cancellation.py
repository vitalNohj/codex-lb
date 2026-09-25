"""Finish owned cleanup even while the surrounding task is being cancelled.

Settlement that writes durable accounting cannot simply run in a ``finally``:
the ``finally`` executes, but inside a cancelled anyio scope (Starlette runs a
streaming body in one) every ``await`` re-raises ``CancelledError``, so work
after the first ``await`` never happens - the reservation stays held and no
request-log row explains it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

import anyio

__all__ = ["await_deferring_cancellation", "complete_despite_cancellation"]

_T = TypeVar("_T")


async def await_deferring_cancellation(awaitable: Awaitable[_T]) -> tuple[_T, bool]:
    """Run ``awaitable`` to completion, deferring cancellation until it finishes.

    Returns ``(result, cancellation_deferred)``. A cancellation delivered while
    the awaitable is in flight is absorbed so the work can finish, and reported
    through the flag so the caller re-raises it once its own required cleanup is
    done - deferred, never swallowed. If the awaitable is itself cancelled, that
    propagates at once. Ordinary failures propagate unchanged.

    This bounds nothing on its own: pass work that already terminates (an owned
    settlement, a stream close), never an open-ended wait.
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


async def complete_despite_cancellation(awaitable: Awaitable[_T]) -> _T:
    """Run ``awaitable`` to completion, then re-raise any cancellation it deferred.

    For cleanup that is the last thing its caller does before unwinding: the
    work always finishes, and a cancelled task still ends cancelled. Callers
    with further required cleanup after this one use
    :func:`await_deferring_cancellation` and re-raise themselves.
    """

    result, cancellation_deferred = await await_deferring_cancellation(awaitable)
    if cancellation_deferred:
        raise asyncio.CancelledError
    return result
