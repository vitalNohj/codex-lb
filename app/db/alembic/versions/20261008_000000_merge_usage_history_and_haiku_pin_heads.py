"""merge usage-history mutation state and Claude Haiku 5.5 pin heads

Revision ID: 20261008_000000_merge_usage_history_and_haiku_pin_heads
Revises: 20261005_000000_add_usage_history_mutation_state, 20261007_000000_pin_claude_haiku_5_5_full_model
Create Date: 2026-10-08
"""

from __future__ import annotations

# revision identifiers, used by Alembic.
revision = "20261008_000000_merge_usage_history_and_haiku_pin_heads"
down_revision = (
    "20261005_000000_add_usage_history_mutation_state",
    "20261007_000000_pin_claude_haiku_5_5_full_model",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
