"""store an API-key limit's model filter as a JSON list

One limit is one shared budget for every model in the list. A NULL filter still
means every model. Existing single-model values are wrapped losslessly:
``gpt-5.1`` becomes ``["gpt-5.1"]`` and still matches only that model.

Downgrade restores the single id. It refuses while any rule names more than
one model, because that set cannot be stored in the old column without
dropping models.

Revision ID: 20261029_000000_api_key_limit_model_filters
Revises: 20261022_000000_merge_fork_and_upstream_1_25_heads
Create Date: 2026-10-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

from app.modules.api_keys.model_filters import downgrade_stored_model_filter, upgrade_stored_model_filter

revision = "20261029_000000_api_key_limit_model_filters"
down_revision = "20261022_000000_merge_fork_and_upstream_1_25_heads"
branch_labels = None
depends_on = None

_TABLE = "api_key_limits"
_COLUMN = "model_filter"


def _columns(connection: Connection) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(_TABLE):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(_TABLE) if column.get("name") is not None}


def _rewrite(convert) -> None:
    bind = op.get_bind()
    if _COLUMN not in _columns(bind):
        return
    rows = bind.execute(sa.text("SELECT id, model_filter FROM api_key_limits")).fetchall()
    # Convert every row before the first write so a refused downgrade changes nothing.
    planned: list[tuple[int, str | None]] = []
    for row in rows:
        current = row.model_filter
        updated = convert(current)
        if updated != current:
            planned.append((row.id, updated))
    statement = sa.text("UPDATE api_key_limits SET model_filter = :value WHERE id = :id")
    for row_id, value in planned:
        bind.execute(statement, {"value": value, "id": row_id})


def upgrade() -> None:
    _rewrite(upgrade_stored_model_filter)


def downgrade() -> None:
    _rewrite(downgrade_stored_model_filter)
