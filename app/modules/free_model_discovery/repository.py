from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FreeModelDiscoveryRun, FreeModelDiscoveryRunItem, FreeModelProbeState
from app.modules.free_model_discovery.candidates import normalize_model_key
from app.modules.free_model_discovery.pacing import cooldown_for_failure_streak

ACTIVE_RUN_STATUS = "running"


class ActiveRunExistsError(Exception):
    """A second run lost the race to start while one was already ``running``.

    Raised when the database's partial unique index rejects the insert, which
    is the authoritative answer: the service's pre-check cannot be, because the
    plan rebuild between check and insert performs provider HTTP calls.
    """


def new_run_id() -> str:
    return str(uuid.uuid4())


class FreeModelDiscoveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- runs -----------------------------------------------------------

    async def get_active_run(self) -> FreeModelDiscoveryRun | None:
        stmt = (
            select(FreeModelDiscoveryRun)
            .where(FreeModelDiscoveryRun.status == ACTIVE_RUN_STATUS)
            .order_by(FreeModelDiscoveryRun.started_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_run(self, run_id: str) -> FreeModelDiscoveryRun | None:
        return await self._session.get(FreeModelDiscoveryRun, run_id)

    async def get_latest_run(self) -> FreeModelDiscoveryRun | None:
        stmt = select(FreeModelDiscoveryRun).order_by(FreeModelDiscoveryRun.started_at.desc()).limit(1)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_runs(self, *, limit: int = 20) -> list[FreeModelDiscoveryRun]:
        stmt = select(FreeModelDiscoveryRun).order_by(FreeModelDiscoveryRun.started_at.desc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())

    async def create_run(
        self,
        *,
        started_at: datetime,
        deadline_at: datetime,
        pacing_floor_seconds: float,
        pacing_cap_seconds: float,
        max_attempts_per_item: int,
        items: Iterable[tuple[str, str, str]],
    ) -> FreeModelDiscoveryRun:
        """Create a run with its frozen candidate set. ``items`` is
        ``(provider, model_id, candidate_group)``."""

        run = FreeModelDiscoveryRun(
            id=new_run_id(),
            status=ACTIVE_RUN_STATUS,
            started_at=started_at,
            deadline_at=deadline_at,
            cancel_requested=False,
            pacing_floor_seconds=pacing_floor_seconds,
            pacing_cap_seconds=pacing_cap_seconds,
            max_attempts_per_item=max_attempts_per_item,
        )
        self._session.add(run)
        for provider, model_id, candidate_group in items:
            self._session.add(
                FreeModelDiscoveryRunItem(
                    run_id=run.id,
                    provider=provider,
                    model_id=model_id,
                    candidate_group=candidate_group,
                    state="queued",
                    attempts=0,
                    next_attempt_at=started_at,
                )
            )
        try:
            await self._session.commit()
        except IntegrityError as exc:
            # The partial unique index on ``status = 'running'`` fired: another
            # request created a run while this one was rebuilding its plan.
            # Roll back so the session stays usable and report it as a lost
            # race rather than a server error.
            await self._session.rollback()
            raise ActiveRunExistsError from exc
        await self._session.refresh(run)
        return run

    async def request_cancel(self, run_id: str) -> bool:
        stmt = (
            update(FreeModelDiscoveryRun)
            .where(FreeModelDiscoveryRun.id == run_id, FreeModelDiscoveryRun.status == ACTIVE_RUN_STATUS)
            .values(cancel_requested=True)
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return int(getattr(result, "rowcount", 0) or 0) > 0

    async def is_cancel_requested(self, run_id: str) -> bool:
        stmt = select(FreeModelDiscoveryRun.cancel_requested).where(FreeModelDiscoveryRun.id == run_id)
        return bool((await self._session.execute(stmt)).scalar_one_or_none())

    async def finish_run(
        self, run_id: str, *, status: str, finished_at: datetime, error_message: str | None = None
    ) -> bool:
        """Terminal transition, guarded on the run still being ``running``.

        Every terminal transition is a compare-and-set on ``status`` so exactly
        one writer can end a run. Several can legitimately race for it: the
        driver's orderly finish, the error path, and - with the runner
        leader-gated but the row shared - another replica. An unguarded UPDATE
        let a finalizer that had already read ``running`` overwrite a terminal
        state another writer had just committed, so a run that died of an
        internal error could be relabelled ``completed`` and lose its
        ``error_message``.

        Queued items are resolved only when the transition actually wins,
        keeping item state consistent with the status the winner wrote.

        Returns whether this call performed the transition.
        """

        result = await self._session.execute(
            update(FreeModelDiscoveryRun)
            .where(FreeModelDiscoveryRun.id == run_id, FreeModelDiscoveryRun.status == ACTIVE_RUN_STATUS)
            .values(status=status, finished_at=finished_at, error_message=error_message)
        )
        if int(getattr(result, "rowcount", 0) or 0) <= 0:
            # Another writer ended this run first; its terminal state stands.
            await self._session.rollback()
            return False
        await self._session.execute(
            update(FreeModelDiscoveryRunItem)
            .where(FreeModelDiscoveryRunItem.run_id == run_id, FreeModelDiscoveryRunItem.state == "queued")
            .values(state="unresolved", resolved_at=finished_at)
        )
        await self._session.commit()
        return True

    async def fail_run(self, run_id: str, *, finished_at: datetime, error_message: str) -> bool:
        """Terminal ``failed`` transition for an unexpected driver error.

        Thin alias over the same guarded transition ``finish_run`` performs, so
        the error path cannot drift from the orderly one.
        """

        return await self.finish_run(run_id, status="failed", finished_at=finished_at, error_message=error_message)

    # --- items ----------------------------------------------------------

    async def list_items(self, run_id: str) -> list[FreeModelDiscoveryRunItem]:
        stmt = (
            select(FreeModelDiscoveryRunItem)
            .where(FreeModelDiscoveryRunItem.run_id == run_id)
            .order_by(FreeModelDiscoveryRunItem.provider, FreeModelDiscoveryRunItem.id)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def next_queued_item(self, run_id: str, provider: str) -> FreeModelDiscoveryRunItem | None:
        """Earliest-due queued item for a provider. ``new`` items are frozen
        first at creation so insertion order already encodes priority."""

        stmt = (
            select(FreeModelDiscoveryRunItem)
            .where(
                FreeModelDiscoveryRunItem.run_id == run_id,
                FreeModelDiscoveryRunItem.provider == provider,
                FreeModelDiscoveryRunItem.state == "queued",
            )
            .order_by(FreeModelDiscoveryRunItem.next_attempt_at, FreeModelDiscoveryRunItem.id)
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def count_queued(self, run_id: str, provider: str) -> int:
        stmt = select(func.count(FreeModelDiscoveryRunItem.id)).where(
            FreeModelDiscoveryRunItem.run_id == run_id,
            FreeModelDiscoveryRunItem.provider == provider,
            FreeModelDiscoveryRunItem.state == "queued",
        )
        return int((await self._session.execute(stmt)).scalar_one() or 0)

    async def record_inconclusive(
        self,
        item: FreeModelDiscoveryRunItem,
        *,
        attempted_at: datetime,
        next_attempt_at: datetime,
        http_status: int | None,
        outcome: str,
    ) -> None:
        item.attempts += 1
        item.last_attempt_at = attempted_at
        item.next_attempt_at = next_attempt_at
        item.last_http_status = http_status
        item.last_outcome = outcome
        await self._session.commit()

    async def mark_unresolved(self, item: FreeModelDiscoveryRunItem, *, resolved_at: datetime, outcome: str) -> None:
        item.state = "unresolved"
        item.resolved_at = resolved_at
        item.last_outcome = outcome
        item.next_attempt_at = None
        await self._session.commit()

    async def record_verdict(
        self,
        item: FreeModelDiscoveryRunItem,
        *,
        verdict: str,
        attempted_at: datetime,
        http_status: int | None,
        outcome: str,
        content_chars: int | None,
        content_ok_match: bool | None,
        reasoning_chars: int | None,
        added_to_full_models: bool,
    ) -> FreeModelProbeState:
        """Persist a verdict on the item and fold it into cross-run state in
        one transaction."""

        item.attempts += 1
        item.state = verdict
        item.last_attempt_at = attempted_at
        item.next_attempt_at = None
        item.last_http_status = http_status
        item.last_outcome = outcome
        item.content_chars = content_chars
        item.content_ok_match = content_ok_match
        item.reasoning_chars = reasoning_chars
        item.added_to_full_models = added_to_full_models
        item.resolved_at = attempted_at

        state = await self._get_state(item.provider, item.model_id)
        if state is None:
            state = FreeModelProbeState(
                provider=item.provider,
                model_id=item.model_id,
                last_verdict=verdict,
                last_verdict_at=attempted_at,
                failure_streak=0,
            )
            self._session.add(state)
        state.last_verdict = verdict
        state.last_verdict_at = attempted_at
        state.last_run_id = item.run_id
        if verdict == "failed":
            state.failure_streak += 1
            state.cooldown_until = attempted_at + cooldown_for_failure_streak(state.failure_streak)
        else:
            state.failure_streak = 0
            state.cooldown_until = None
        await self._session.commit()
        return state

    # --- cross-run state -----------------------------------------------

    async def _get_state(self, provider: str, model_id: str) -> FreeModelProbeState | None:
        key = normalize_model_key(model_id)
        stmt = select(FreeModelProbeState).where(
            FreeModelProbeState.provider == provider,
            func.lower(FreeModelProbeState.model_id) == key,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def states_for_provider(self, provider: str) -> dict[str, FreeModelProbeState]:
        stmt = select(FreeModelProbeState).where(FreeModelProbeState.provider == provider)
        rows = (await self._session.execute(stmt)).scalars().all()
        return {normalize_model_key(row.model_id): row for row in rows}

    async def unresolved_keys_for_provider(self, provider: str, *, run: FreeModelDiscoveryRun | None) -> set[str]:
        """Keys the given (latest finished) run could not resolve."""

        if run is None:
            return set()
        stmt = select(FreeModelDiscoveryRunItem.model_id).where(
            FreeModelDiscoveryRunItem.run_id == run.id,
            FreeModelDiscoveryRunItem.provider == provider,
            FreeModelDiscoveryRunItem.state == "unresolved",
        )
        rows: Sequence[str] = (await self._session.execute(stmt)).scalars().all()
        return {normalize_model_key(model_id) for model_id in rows}
