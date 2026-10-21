"""add the one-time lifetime api key limit window

A lifetime limit never resets: it is a one-time budget for a key, topped up by
raising its maximum. PostgreSQL stores limit windows in the native
``limit_window`` enum, so the value has to be added there. SQLite stores the
window as plain text, so it needs no change.

PostgreSQL cannot drop an enum value in place, so the downgrade leaves it.
Rows that use it would otherwise be orphaned; an operator downgrading past
this revision must delete lifetime limits first.

Revision ID: 20261021_000000_add_lifetime_api_key_limit_window
Revises: 20261020_010000_add_api_key_is_shared
Create Date: 2026-10-21 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20261021_000000_add_lifetime_api_key_limit_window"
down_revision = "20261020_010000_add_api_key_is_shared"
branch_labels = None
depends_on = None


def _table_exists(connection: Connection, table_name: str) -> bool:
    inspector = sa.inspect(connection)
    return inspector.has_table(table_name)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if not _table_exists(bind, "api_key_limits"):
        return
    with op.get_context().autocommit_block():
        op.execute(sa.text("ALTER TYPE limit_window ADD VALUE IF NOT EXISTS 'lifetime'"))


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely in place, and SQLite
    # never had one.
    return
