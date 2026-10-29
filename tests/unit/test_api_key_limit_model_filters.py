from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.modules.api_keys.model_filters import (
    ModelFilterDowngradeError,
    decode_model_filters,
    model_filter_quota_token,
    upgrade_stored_model_filter,
)

pytestmark = pytest.mark.unit

_MIGRATION = importlib.import_module("app.db.alembic.versions.20261029_000000_api_key_limit_model_filters")


def _engine(tmp_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{tmp_path / 'limits.sqlite'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE api_key_limits (id INTEGER PRIMARY KEY, model_filter VARCHAR)"))
    return engine


def _insert(engine: Engine, rows: list[tuple[int, str | None]]) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO api_key_limits (id, model_filter) VALUES (:id, :model_filter)"),
            [{"id": row_id, "model_filter": value} for row_id, value in rows],
        )


def _stored(engine: Engine) -> dict[int, str | None]:
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, model_filter FROM api_key_limits ORDER BY id")).all()
    return {int(row.id): row.model_filter for row in rows}


def _run(engine: Engine, revision_fn) -> None:
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            revision_fn()


def test_upgrade_wraps_every_legacy_id_including_json_looking_text(tmp_path: Path) -> None:
    json_looking = '["gpt-5.4"]'
    empty_list = "[]"
    engine = _engine(tmp_path)
    _insert(
        engine,
        [
            (1, "gpt-5.1"),
            (2, None),
            (3, json_looking),
            (4, empty_list),
        ],
    )

    _run(engine, _MIGRATION.upgrade)

    stored = _stored(engine)
    assert stored[1] == '["gpt-5.1"]'
    assert stored[2] is None
    assert decode_model_filters(stored[3]) == [json_looking]
    assert decode_model_filters(stored[4]) == [empty_list]
    assert upgrade_stored_model_filter("gpt-5.1") == '["gpt-5.1"]'
    assert upgrade_stored_model_filter(empty_list) == '["[]"]'
    assert decode_model_filters(upgrade_stored_model_filter('["model-alpha"]')) == ['["model-alpha"]']

    _run(engine, _MIGRATION.downgrade)

    assert _stored(engine) == {
        1: "gpt-5.1",
        2: None,
        3: json_looking,
        4: empty_list,
    }


def test_downgrade_refuses_a_multi_model_rule_without_writing(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    _insert(
        engine,
        [
            (1, "gpt-5.1"),
            (2, '["gpt-5.1","gpt-5.4"]'),
        ],
    )

    with pytest.raises(ModelFilterDowngradeError, match="gpt-5.1, gpt-5.4"):
        _run(engine, _MIGRATION.downgrade)

    assert _stored(engine) == {
        1: "gpt-5.1",
        2: '["gpt-5.1","gpt-5.4"]',
    }


def test_upgrade_pages_past_the_first_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_MIGRATION, "_BATCH_SIZE", 2)
    engine = _engine(tmp_path)
    json_looking = '["gpt-5.4"]'
    _insert(engine, [(1, "gpt-5.1"), (2, None), (3, "gpt-5.4"), (4, "gpt-5"), (5, json_looking)])

    _run(engine, _MIGRATION.upgrade)

    stored = _stored(engine)
    assert stored[1] == '["gpt-5.1"]'
    assert stored[2] is None
    assert stored[3] == '["gpt-5.4"]'
    assert stored[4] == '["gpt-5"]'
    assert decode_model_filters(stored[5]) == [json_looking]


def test_quota_token_keeps_one_model_bare_and_sorts_a_set() -> None:
    assert model_filter_quota_token([]) is None
    assert model_filter_quota_token(["gpt-5.1"]) == "gpt-5.1"
    assert model_filter_quota_token(["gpt-5.4", "gpt-5.1"]) == "gpt-5.1,gpt-5.4"
