"""Behavioral tests for the full-model stars migration.

The migration adds ``sidecar_full_model_stars_json`` and seeds it so every
full model configured before the upgrade becomes starred on the card that
already owned it: pre-stars, the save-time uniqueness check guaranteed at most
one card per full model, so this changes no routing. A row that already
carries a star map (replayed legacy remap) must keep it byte-identical.

These drive the real ``upgrade()`` against a synthetic SQLite database, the
same pattern as ``test_single_active_discovery_run_migration.py``.
"""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

migration = import_module("app.db.alembic.versions.20261005_000000_add_full_model_stars")

pytestmark = pytest.mark.unit

_TABLE = "dashboard_settings"
_STARS = "sidecar_full_model_stars_json"

_CREATE_TABLE = f"""
CREATE TABLE {_TABLE} (
    id VARCHAR NOT NULL PRIMARY KEY,
    claude_sidecar_full_models_json TEXT NOT NULL DEFAULT '[]',
    openrouter_sidecar_full_models_json TEXT NOT NULL DEFAULT '[]',
    orcarouter_sidecar_full_models_json TEXT NOT NULL DEFAULT '[]',
    opencode_go_sidecar_full_models_json TEXT NOT NULL DEFAULT '[]',
    omniroute_sidecar_full_models_json TEXT NOT NULL DEFAULT '[]',
    ollama_sidecar_full_models_json TEXT NOT NULL DEFAULT '[]',
    openai_compat_endpoints_json TEXT NOT NULL DEFAULT '[]',
    {_STARS} TEXT NOT NULL DEFAULT '{{}}'
)
"""


def _seed_row(con: Any, row_id: str, **columns: str) -> None:
    names = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    con.execute(
        f"INSERT INTO {_TABLE} (id, {names}) VALUES (?, {placeholders})",
        (row_id, *columns.values()),
    )


def _run_upgrade(db_path: Path) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()
    finally:
        engine.dispose()


def _stars(db_path: Path, row_id: str) -> dict[str, str]:
    con = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with con.connect() as connection:
            raw = connection.execute(
                sa.text(f"SELECT {_STARS} FROM {_TABLE} WHERE id = :id"),
                {"id": row_id},
            ).scalar_one()
        return json.loads(raw)
    finally:
        con.dispose()


def _seeded_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "settings.db"
    raw_con = __import__("sqlite3").connect(db_path)
    try:
        raw_con.execute(_CREATE_TABLE)
        raw_con.commit()
    finally:
        raw_con.close()
    return db_path


def test_upgrade_seeds_every_existing_full_model_with_its_current_card(tmp_path: Path) -> None:
    db_path = _seeded_db(tmp_path)
    raw_con = __import__("sqlite3").connect(db_path)
    try:
        _seed_row(
            raw_con,
            "row-1",
            openrouter_sidecar_full_models_json=json.dumps(["z-ai/glm-5.3", "DeepSeek/Chat"]),
            orcarouter_sidecar_full_models_json=json.dumps(["ollama/cloud/gpt-oss"]),
            ollama_sidecar_full_models_json=json.dumps(["llama3:70b"]),
            openai_compat_endpoints_json=json.dumps(
                [{"id": "ep-1", "name": "Vast", "full_models": json.dumps(["Qwen/Qwen2.5-7B"])}]
            ),
        )
        raw_con.commit()
    finally:
        raw_con.close()

    _run_upgrade(db_path)

    # Pre-stars, at most one card could own each model, so the seeded star is
    # that card and today's routing is unchanged after the upgrade.
    assert _stars(db_path, "row-1") == {
        "z-ai/glm-5.3": "openrouter",
        "deepseek/chat": "openrouter",
        "ollama/cloud/gpt-oss": "orcarouter",
        "llama3:70b": "ollama",
        "qwen/qwen2.5-7b": "openai_compat:ep-1",
    }


def test_upgrade_keeps_an_existing_star_map_byte_identical(tmp_path: Path) -> None:
    db_path = _seeded_db(tmp_path)
    existing = json.dumps({"z-ai/glm-5.3": "orcarouter"}, sort_keys=True, separators=(",", ":"))
    raw_con = __import__("sqlite3").connect(db_path)
    try:
        _seed_row(
            raw_con,
            "row-1",
            openrouter_sidecar_full_models_json=json.dumps(["z-ai/glm-5.3"]),
            **{_STARS: existing},
        )
        raw_con.commit()
    finally:
        raw_con.close()

    _run_upgrade(db_path)

    assert _stars(db_path, "row-1") == {"z-ai/glm-5.3": "orcarouter"}


def test_upgrade_leaves_a_row_without_full_models_alone(tmp_path: Path) -> None:
    db_path = _seeded_db(tmp_path)
    raw_con = __import__("sqlite3").connect(db_path)
    try:
        raw_con.execute(f"INSERT INTO {_TABLE} (id) VALUES ('row-1')")
        raw_con.commit()
    finally:
        raw_con.close()

    _run_upgrade(db_path)

    assert _stars(db_path, "row-1") == {}


def test_upgrade_adds_the_missing_column(tmp_path: Path) -> None:
    db_path = tmp_path / "settings.db"
    raw_con = __import__("sqlite3").connect(db_path)
    try:
        raw_con.execute(f"CREATE TABLE {_TABLE} (id VARCHAR NOT NULL PRIMARY KEY)")
        raw_con.execute(f"INSERT INTO {_TABLE} (id) VALUES ('row-1')")
        raw_con.commit()
    finally:
        raw_con.close()

    _run_upgrade(db_path)

    assert _stars(db_path, "row-1") == {}
