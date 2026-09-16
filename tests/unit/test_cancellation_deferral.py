"""Cancellation deferral must finish the cleanup AND still cancel the caller."""

from __future__ import annotations

import asyncio

import pytest

from app.core.utils.cancellation import (
    await_cleanup_deferring_cancellation,
    await_result_deferring_cancellation,
)


async def test_cleanup_completes_and_cancellation_is_re_raised() -> None:
    """The deferral must not swallow the caller's cancellation.

    Absorbing it so the cleanup can finish is the point; returning normally
    afterwards is not. A request cancelled mid-settlement must still terminate
    as cancelled, or callers below it would treat it as a completed request.
    """

    settled: list[str] = []

    async def cleanup() -> str:
        await asyncio.sleep(0.05)
        settled.append("settled")
        return "done"

    async def caller() -> str:
        await await_cleanup_deferring_cancellation(cleanup())
        return "completed-normally"

    task = asyncio.create_task(caller())
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    # Both halves of the contract: the cleanup ran to completion...
    assert settled == ["settled"]
    # ...and the caller did not finish normally (asserted by pytest.raises).


async def test_result_variant_reports_deferred_cancellation() -> None:
    """The result variant hands the flag back so callers can re-raise themselves."""

    async def cleanup() -> str:
        await asyncio.sleep(0.05)
        return "done"

    observed: list[tuple[str, bool]] = []

    async def caller() -> None:
        observed.append(await await_result_deferring_cancellation(cleanup()))

    task = asyncio.create_task(caller())
    await asyncio.sleep(0.01)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert observed == [("done", True)], "deferred cancellation was not reported to the caller"


async def test_uncancelled_cleanup_returns_normally() -> None:
    """Control: with no cancellation, nothing is deferred and nothing is raised."""

    async def cleanup() -> str:
        return "done"

    assert await await_cleanup_deferring_cancellation(cleanup()) == "done"
    assert await await_result_deferring_cancellation(cleanup()) == ("done", False)


async def test_cancelling_the_cleanup_itself_propagates_immediately() -> None:
    """A cleanup that is itself cancelled must not be reported as completed."""

    async def cleanup() -> str:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await await_cleanup_deferring_cancellation(cleanup())


async def test_ordinary_failures_are_not_suppressed() -> None:
    """Errors inside the cleanup propagate unchanged - nothing is swallowed."""

    async def cleanup() -> str:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await await_cleanup_deferring_cancellation(cleanup())
