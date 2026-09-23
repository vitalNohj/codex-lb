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


def _rewrite(bind: Connection, transform: Callable[[str | None], str | None]) -> None:
    if _COLUMN_NAME not in _columns(bind, _TABLE_NAME):
        return
    rows = bind.execute(sa.text(f"SELECT id, {_COLUMN_NAME} FROM {_TABLE_NAME}")).fetchall()
    for row in rows:
        updated = transform(row[1])
        if updated is None or updated == row[1]:
            continue
        bind.execute(
            sa.text(f"UPDATE {_TABLE_NAME} SET {_COLUMN_NAME} = :value WHERE id = :id"),
            {"value": updated, "id": row[0]},
        )


def upgrade() -> None:
    _rewrite(op.get_bind(), _append_model)


def downgrade() -> None:
    _rewrite(op.get_bind(), _remove_model)
