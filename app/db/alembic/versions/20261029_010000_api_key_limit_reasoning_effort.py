"""let an API-key limit rule force a reasoning effort

A rule may force an effort with or without a spending budget. Existing rules
keep a null effort and their budgets, so they behave exactly as before.
Effort-only rules store no type, window, maximum, or reset time.

Downgrade drops the effort and restores the budget columns as required. It
refuses while any rule has no budget, because that row cannot be represented
again.

Revision ID: 20261029_010000_api_key_limit_reasoning_effort
Revises: 20261029_000000_api_key_limit_model_filters
Create Date: 2026-10-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20261029_010000_api_key_limit_reasoning_effort"
down_revision = "20261029_000000_api_key_limit_model_filters"
branch_labels = None
depends_on = None

_TABLE = "api_key_limits"
_EFFORT = "reasoning_effort"
_BUDGET_COLUMNS = ("limit_type", "limit_window", "max_value", "reset_at")


class LimitReasoningEffortDowngradeError(RuntimeError):
    """An effort-only rule cannot be stored once budget columns are required."""


def _columns(connection: Connection) -> dict[str, dict[str, object]]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(_TABLE):
        return {}
    return {
        str(column["name"]): column
        for column in inspector.get_columns(_TABLE)
        if column.get("name") is not None
    }


def upgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind)
    if not columns:
        return
    with op.batch_alter_table(_TABLE) as batch_op:
        if _EFFORT not in columns:
            batch_op.add_column(sa.Column(_EFFORT, sa.String(), nullable=True))
        for name in _BUDGET_COLUMNS:
            column = columns.get(name)
            if column is None or column.get("nullable") is True:
                continue
            batch_op.alter_column(name, existing_type=column["type"], nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind)
    if not columns:
        return
    if all(name in columns for name in _BUDGET_COLUMNS):
        effort_only = bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM api_key_limits "
                "WHERE limit_type IS NULL OR limit_window IS NULL OR max_value IS NULL OR reset_at IS NULL"
            )
        ).scalar_one()
        if effort_only:
            raise LimitReasoningEffortDowngradeError(
                "cannot downgrade api_key_limits while a rule has no spending budget"
            )
    with op.batch_alter_table(_TABLE) as batch_op:
        if _EFFORT in columns:
            batch_op.drop_column(_EFFORT)
        for name in _BUDGET_COLUMNS:
            column = columns.get(name)
            if column is None or column.get("nullable") is not True:
                continue
            batch_op.alter_column(name, existing_type=column["type"], nullable=False)
