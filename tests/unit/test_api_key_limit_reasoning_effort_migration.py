from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.unit

_MIGRATION = importlib.import_module("app.db.alembic.versions.20261029_010000_api_key_limit_reasoning_effort")


def _engine(tmp_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{tmp_path / 'limits.sqlite'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE api_key_limits ("
                "id INTEGER PRIMARY KEY, "
                "limit_type VARCHAR NOT NULL, "
                "limit_window VARCHAR NOT NULL, "
                "max_value INTEGER NOT NULL, "
                "current_value INTEGER NOT NULL, "
                "model_filter VARCHAR, "
                "reset_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO api_key_limits "
                "(id, limit_type, limit_window, max_value, current_value, model_filter, reset_at) "
                "VALUES (1, 'total_tokens', 'weekly', 1000, 0, NULL, '2026-02-01 00:00:00')"
            )
        )
    return engine


def _run(engine: Engine, revision_fn) -> None:
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            revision_fn()


def _nullable(engine: Engine, name: str) -> bool | None:
    row = inspect(engine).get_columns("api_key_limits")
    column = next(item for item in row if item["name"] == name)
    nullable = column.get("nullable")
    return nullable if isinstance(nullable, bool) else None


def test_upgrade_adds_a_null_effort_and_allows_an_effort_only_rule(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    _run(engine, _MIGRATION.upgrade)

    assert _nullable(engine, "reasoning_effort") is True
    assert _nullable(engine, "limit_type") is True
    assert _nullable(engine, "max_value") is True
    assert _nullable(engine, "reset_at") is True
    with engine.connect() as connection:
        existing = connection.execute(text("SELECT reasoning_effort FROM api_key_limits WHERE id = 1")).scalar_one()
    assert existing is None

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO api_key_limits "
                "(id, limit_type, limit_window, max_value, current_value, model_filter, reset_at, reasoning_effort) "
                "VALUES (2, NULL, NULL, NULL, 0, :model_filter, NULL, 'max')"
            ),
            {"model_filter": '["gpt-5.3-codex"]'},
        )

    with pytest.raises(_MIGRATION.LimitReasoningEffortDowngradeError, match="no spending budget"):
        _run(engine, _MIGRATION.downgrade)

    assert _nullable(engine, "reasoning_effort") is True


def test_downgrade_restores_required_budget_columns_when_every_rule_has_one(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    _run(engine, _MIGRATION.upgrade)
    with engine.begin() as connection:
        connection.execute(text("UPDATE api_key_limits SET reasoning_effort = 'high' WHERE id = 1"))

    _run(engine, _MIGRATION.downgrade)

    names = {column["name"] for column in inspect(engine).get_columns("api_key_limits")}
    assert "reasoning_effort" not in names
    assert _nullable(engine, "limit_type") is False
    assert _nullable(engine, "limit_window") is False
    assert _nullable(engine, "max_value") is False
    assert _nullable(engine, "reset_at") is False
