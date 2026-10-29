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

from collections.abc import Iterator, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection, Row

from app.modules.api_keys.model_filters import downgrade_stored_model_filter, upgrade_stored_model_filter

revision = "20261029_000000_api_key_limit_model_filters"
down_revision = "20261022_000000_merge_fork_and_upstream_1_25_heads"
branch_labels = None
depends_on = None

_TABLE = "api_key_limits"
_COLUMN = "model_filter"
# Two bound parameters per row. 250 stays under SQLite's default 999-variable limit.
_BATCH_SIZE = 250

_PAGE = sa.text("SELECT id, model_filter FROM api_key_limits WHERE id > :last_id ORDER BY id LIMIT :batch_size")
_UPDATE = sa.text("UPDATE api_key_limits SET model_filter = :value WHERE id = :id")


def _columns(connection: Connection) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(_TABLE):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(_TABLE) if column.get("name") is not None}


def _pages(bind: Connection) -> Iterator[Sequence[Row[Any]]]:
    last_id = 0
    while True:
        rows = bind.execute(_PAGE, {"last_id": last_id, "batch_size": _BATCH_SIZE}).fetchall()
        if not rows:
            return
        yield rows
        last_id = int(rows[-1].id)


def _rewrite(convert) -> None:
    bind = op.get_bind()
    if _COLUMN not in _columns(bind):
        return
    # Convert every row before the first write so a refused downgrade changes nothing.
    for rows in _pages(bind):
        for row in rows:
            convert(row.model_filter)
    for rows in _pages(bind):
        planned = [
            {"value": updated, "id": row.id}
            for row in rows
            if (updated := convert(row.model_filter)) != row.model_filter
        ]
        if planned:
            bind.execute(_UPDATE, planned)


def upgrade() -> None:
    _rewrite(upgrade_stored_model_filter)


def downgrade() -> None:
    _rewrite(downgrade_stored_model_filter)
