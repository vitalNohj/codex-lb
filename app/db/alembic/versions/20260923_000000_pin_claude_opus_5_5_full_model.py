"""pin claude-opus-5-5 on the CLIProxyAPI full-model list

Revision ID: 20260923_000000_pin_claude_opus_5_5_full_model
Revises: 20260919_000000_add_openai_compat_endpoints
Create Date: 2026-09-23 00:00:00.000000
"""

from __future__ import annotations

import json
from collections.abc import Callable

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20260923_000000_pin_claude_opus_5_5_full_model"
down_revision = "20260919_000000_add_openai_compat_endpoints"
branch_labels = None
depends_on = None

_TABLE_NAME = "dashboard_settings"
_COLUMN_NAME = "claude_sidecar_full_models_json"
_MODEL_ID = "claude-opus-5-5"
_OWNERSHIP_TABLE = "claude_opus_5_5_pin_ownership"
_BATCH_SIZE = 250


def _columns(connection: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name) if column.get("name") is not None}


def _load_entries(raw: str | None) -> list[object] | None:
    if raw is None or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    return parsed


def _contains_model(entries: list[object]) -> bool:
    return any(isinstance(entry, str) and entry.strip().lower() == _MODEL_ID for entry in entries)


def _append_model(raw: str | None) -> str | None:
    entries = _load_entries(raw)
    if entries is None or _contains_model(entries):
        return None
    return json.dumps([*entries, _MODEL_ID], separators=(",", ":"))


def _remove_model(raw: str | None) -> str | None:
    entries = _load_entries(raw)
    if entries is None:
        return None
    kept = [entry for entry in entries if not (isinstance(entry, str) and entry.strip().lower() == _MODEL_ID)]
    if len(kept) == len(entries):
        return None
    return json.dumps(kept, separators=(",", ":"))


def _setting_text(raw: object) -> str | None:
    if raw is None or isinstance(raw, str):
        return raw
    return str(raw)


def _apply_batches(bind: Connection, transform: Callable[[str | None], str | None], *, owned_only: bool) -> None:
    last_id = 0
    ownership_join = f"INNER JOIN {_OWNERSHIP_TABLE} AS owned ON owned.settings_id = settings.id" if owned_only else ""
    while True:
        batch = bind.execute(
            sa.text(
                f"SELECT settings.id, settings.{_COLUMN_NAME} "
                f"FROM {_TABLE_NAME} AS settings {ownership_join} "
                "WHERE settings.id > :last_id ORDER BY settings.id LIMIT :limit"
            ),
            {"last_id": last_id, "limit": _BATCH_SIZE},
        ).fetchall()
        if not batch:
            return
        for row in batch:
            updated = transform(_setting_text(row[1]))
            if updated is None:
                continue
            bind.execute(
                sa.text(f"UPDATE {_TABLE_NAME} SET {_COLUMN_NAME} = :value WHERE id = :id"),
                {"value": updated, "id": row[0]},
            )
            if not owned_only:
                bind.execute(
                    sa.text(f"INSERT INTO {_OWNERSHIP_TABLE} (settings_id) VALUES (:id)"),
                    {"id": row[0]},
                )
        last_id = int(batch[-1][0])
        if len(batch) < _BATCH_SIZE:
            return


def upgrade() -> None:
    bind = op.get_bind()
    if _COLUMN_NAME not in _columns(bind, _TABLE_NAME):
        return
    op.create_table(
        _OWNERSHIP_TABLE,
        sa.Column("settings_id", sa.Integer(), primary_key=True),
    )
    _apply_batches(bind, _append_model, owned_only=False)


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table(_OWNERSHIP_TABLE) and _COLUMN_NAME in _columns(bind, _TABLE_NAME):
        _apply_batches(bind, _remove_model, owned_only=True)
    if sa.inspect(bind).has_table(_OWNERSHIP_TABLE):
        op.drop_table(_OWNERSHIP_TABLE)
