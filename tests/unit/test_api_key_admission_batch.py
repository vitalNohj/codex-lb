"""Admission writes one statement per table, and concurrent reserves cannot overspend."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

import app.db.session as session_module
from app.db.models import ApiKeyLimit, Base
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import (
    ApiKeyCreateData,
    ApiKeyData,
    ApiKeyInvalidError,
    ApiKeyRateLimitExceededError,
    ApiKeyRequestUsageBudget,
    ApiKeyUpdateData,
    ApiKeysService,
    LimitRuleInput,
)

pytestmark = pytest.mark.unit


class _Unlocked:
    async def acquire(self) -> None:
        return None

    def release(self) -> None:
        return None


@asynccontextmanager
async def _file_engine(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_path = tmp_path / "admission.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        **session_module._sqlite_file_async_engine_kwargs(),
    )
    session_module._configure_sqlite_engine(engine.sync_engine, enable_wal=True)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@contextmanager
def _capture_statements(engine: AsyncEngine) -> Iterator[list[str]]:
    statements: list[str] = []

    def _record(_conn, _cursor, statement: str, _parameters, _context, _executemany) -> None:  # type: ignore[no-untyped-def]
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _record)


def _mentions_api_keys_table(statement: str) -> bool:
    normalized = " ".join(statement.lower().split())
    return (
        " from api_keys " in f" {normalized} "
        or " update api_keys " in f" {normalized} "
        or " into api_keys " in f" {normalized} "
    )


async def _create_limited_key(
    factory: async_sessionmaker[AsyncSession],
    *,
    rules: list[LimitRuleInput],
) -> ApiKeyData:
    async with factory() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        return await service.create_key(
            ApiKeyCreateData(
                name="admission-batch",
                allowed_models=None,
                expires_at=None,
                limits=rules,
            )
        )


@pytest.mark.asyncio
async def test_two_limit_rules_use_one_write_each_and_one_key_read(tmp_path: Path) -> None:
    database_path = tmp_path / "statements.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        **session_module._sqlite_file_async_engine_kwargs(),
    )
    session_module._configure_sqlite_engine(engine.sync_engine, enable_wal=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        created = await _create_limited_key(
            factory,
            rules=[
                LimitRuleInput(limit_type="total_tokens", limit_window="daily", max_value=10_000),
                LimitRuleInput(limit_type="input_tokens", limit_window="weekly", max_value=10_000),
            ],
        )
        budget = ApiKeyRequestUsageBudget(input_tokens=100, output_tokens=50)

        with _capture_statements(engine) as reserve_statements:
            async with factory() as session:
                service = ApiKeysService(ApiKeysRepository(session))
                reservation = await service.enforce_limits_for_request(
                    created.id,
                    request_model="gpt-5.4",
                    request_usage_budget=budget,
                    admission_key=created,
                )
        assert reservation is not None
        # One current-row read validates existence, is_active, and expires_at.
        # The cached admission key must not replace that read.
        assert sum(1 for statement in reserve_statements if _mentions_api_keys_table(statement)) == 1
        assert (
            sum(1 for statement in reserve_statements if "update api_key_limits" in statement.lower()) == 1
        )
        assert (
            sum(
                1
                for statement in reserve_statements
                if "into api_key_usage_reservation_items" in statement.lower()
            )
            == 1
        )

        with _capture_statements(engine) as settle_statements:
            async with factory() as session:
                service = ApiKeysService(ApiKeysRepository(session))
                await service.finalize_usage_reservation(
                    reservation.reservation_id,
                    model="gpt-5.4",
                    input_tokens=100,
                    output_tokens=50,
                )
        item_statements = [
            statement
            for statement in settle_statements
            if "api_key_usage_reservation_items" in statement.lower()
        ]
        assert len(item_statements) == 1
        assert item_statements[0].lstrip().lower().startswith("insert")
        assert not any(statement.lstrip().lower().startswith("select") for statement in item_statements)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sequential_requests_clip_to_the_remaining_budget(tmp_path: Path) -> None:
    async with _file_engine(tmp_path) as factory:
        created = await _create_limited_key(
            factory,
            rules=[LimitRuleInput(limit_type="total_tokens", limit_window="daily", max_value=100)],
        )
        budget = ApiKeyRequestUsageBudget(input_tokens=80, output_tokens=0)

        async def admit() -> bool:
            async with factory() as session:
                service = ApiKeysService(ApiKeysRepository(session))
                try:
                    reservation = await service.enforce_limits_for_request(
                        created.id,
                        request_model="gpt-5.4",
                        request_usage_budget=budget,
                        admission_key=created,
                    )
                except ApiKeyRateLimitExceededError:
                    return False
                return reservation is not None

        assert await admit() is True
        assert await admit() is True
        async with factory() as session:
            limit = (
                await session.execute(select(ApiKeyLimit).where(ApiKeyLimit.api_key_id == created.id))
            ).scalar_one()
        assert limit.current_value == 100


@pytest.mark.asyncio
async def test_overlapped_reserves_do_not_overspend_the_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both requests price an 80 delta off current=0. The counter must stay <= max."""
    monkeypatch.setattr(session_module, "_file_sqlite_writer_lock", lambda: _Unlocked())
    async with _file_engine(tmp_path) as factory:
        created = await _create_limited_key(
            factory,
            rules=[LimitRuleInput(limit_type="total_tokens", limit_window="daily", max_value=100)],
        )
        budget = ApiKeyRequestUsageBudget(input_tokens=80, output_tokens=0)
        seen_deltas: list[list[int]] = []
        arrived = 0
        gate = asyncio.Event()
        original = ApiKeysRepository.try_reserve_usage_many

        async def _overlapped(self: ApiKeysRepository, reservations: list[tuple[int, int, object]]) -> dict:
            nonlocal arrived
            seen_deltas.append([delta for _limit_id, delta, _reset_at in reservations])
            arrived += 1
            if arrived >= 2:
                gate.set()
            await asyncio.wait_for(gate.wait(), timeout=5)
            return await original(self, reservations)  # type: ignore[arg-type]

        monkeypatch.setattr(ApiKeysRepository, "try_reserve_usage_many", _overlapped)

        async def admit() -> bool:
            async with factory() as session:
                service = ApiKeysService(ApiKeysRepository(session))
                try:
                    reservation = await service.enforce_limits_for_request(
                        created.id,
                        request_model="gpt-5.4",
                        request_usage_budget=budget,
                        admission_key=created,
                    )
                except ApiKeyRateLimitExceededError:
                    return False
                return reservation is not None

        first, second = await asyncio.gather(admit(), admit())
        async with factory() as session:
            limit = (
                await session.execute(select(ApiKeyLimit).where(ApiKeyLimit.api_key_id == created.id))
            ).scalar_one()

        assert seen_deltas[0] == [80]
        assert seen_deltas[1] == [80]
        assert limit.current_value <= 100
        assert limit.current_value == 80
        assert [first, second].count(True) == 1


async def test_cached_admission_key_is_rejected_after_revoke_delete_or_expiry(tmp_path: Path) -> None:
    async with _file_engine(tmp_path) as factory:
        async with factory() as session:
            created = await ApiKeysService(ApiKeysRepository(session)).create_key(
                ApiKeyCreateData(
                    name="cached",
                    allowed_models=None,
                    limits=[LimitRuleInput(limit_type="total_tokens", limit_window="daily", max_value=100)],
                )
            )

        async with factory() as session:
            service = ApiKeysService(ApiKeysRepository(session))
            await service.update_key(created.id, ApiKeyUpdateData(is_active=False, is_active_set=True))
            with pytest.raises(ApiKeyInvalidError, match="Invalid API key"):
                await service.enforce_limits_for_request(
                    created.id,
                    request_model="gpt-5.4",
                    request_usage_budget=ApiKeyRequestUsageBudget(input_tokens=10, output_tokens=0),
                    admission_key=created,
                )
            await service.update_key(created.id, ApiKeyUpdateData(is_active=True, is_active_set=True))

        past = datetime(2020, 1, 1)
        async with factory() as session:
            service = ApiKeysService(ApiKeysRepository(session))
            await service.update_key(
                created.id,
                ApiKeyUpdateData(expires_at=past, expires_at_set=True),
            )
            with pytest.raises(ApiKeyInvalidError, match="API key has expired"):
                await service.enforce_limits_for_request(
                    created.id,
                    request_model="gpt-5.4",
                    request_usage_budget=ApiKeyRequestUsageBudget(input_tokens=10, output_tokens=0),
                    admission_key=created,
                )
            await service.update_key(created.id, ApiKeyUpdateData(expires_at=None, expires_at_set=True))

        stale = created
        async with factory() as session:
            await ApiKeysService(ApiKeysRepository(session)).delete_key(created.id)
        async with factory() as session:
            with pytest.raises(ApiKeyInvalidError, match="Invalid API key"):
                await ApiKeysService(ApiKeysRepository(session)).enforce_limits_for_request(
                    created.id,
                    request_model="gpt-5.4",
                    request_usage_budget=ApiKeyRequestUsageBudget(input_tokens=10, output_tokens=0),
                    admission_key=stale,
                )
