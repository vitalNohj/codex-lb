from __future__ import annotations

import json
from importlib import import_module

import pytest
import sqlalchemy as sa

migration = import_module("app.db.alembic.versions.20260618_040000_unify_sidecar_routing_settings")

pytestmark = pytest.mark.unit


def test_upgrade_prefix_normalization_converts_strings_and_seeds_cli_aliases() -> None:
    upgraded = migration._normalize_prefix_rows(json.dumps(["Claude", "cp-", "cp-"]), seed_claude_aliases=True)

    assert json.loads(upgraded) == [
        {"prefix": "claude", "strip": False},
        {"prefix": "cp-", "strip": True},
        {"prefix": "cp_", "strip": True},
    ]


def test_upgrade_prefix_normalization_preserves_object_strip_flags() -> None:
    upgraded = migration._normalize_prefix_rows(
        json.dumps(
            [
                {"prefix": "or-", "strip": False},
                {"prefix": "OpenRouter/", "strip": True},
            ]
        )
    )

    assert json.loads(upgraded) == [
        {"prefix": "or-", "strip": False},
        {"prefix": "openrouter/", "strip": True},
    ]


def test_downgrade_prefix_collapse_returns_string_arrays() -> None:
    downgraded = migration._collapse_prefix_rows(
        json.dumps(
            [
                {"prefix": "claude", "strip": False},
                {"prefix": "cp-", "strip": True},
                "legacy/",
            ]
        )
    )

    assert json.loads(downgraded) == ["claude", "cp-", "legacy/"]


def test_settings_rows_are_read_and_rewritten_in_bounded_batches() -> None:
    engine = sa.create_engine("sqlite://")
    row_count = migration._BATCH_SIZE * 2 + 50
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE dashboard_settings (id INTEGER PRIMARY KEY, prefixes TEXT)"))
        connection.execute(
            sa.text("INSERT INTO dashboard_settings (id, prefixes) VALUES (:id, :prefixes)"),
            [{"id": row_id, "prefixes": json.dumps(["Claude"])} for row_id in range(1, row_count + 1)],
        )

        batches = list(migration._settings_row_batches(connection, ("prefixes",)))
        migration._rewrite_settings_column(connection, "prefixes", migration._normalize_prefix_rows)
        rewritten = connection.execute(sa.text("SELECT id, prefixes FROM dashboard_settings")).all()

    assert [len(batch) for batch in batches] == [migration._BATCH_SIZE, migration._BATCH_SIZE, 50]
    assert [row["id"] for batch in batches for row in batch] == list(range(1, row_count + 1))
    assert len(rewritten) == row_count
    assert all(json.loads(prefixes) == [{"prefix": "claude", "strip": False}] for _, prefixes in rewritten)
