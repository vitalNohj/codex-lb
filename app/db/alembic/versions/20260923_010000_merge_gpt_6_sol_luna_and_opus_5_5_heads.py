"""merge the GPT-6 Sol/Luna cost backfill and Opus 5.5 pin heads

Revision ID: 20260923_010000_merge_gpt_6_sol_luna_and_opus_5_5_heads
Revises: 20260922_000000_backfill_gpt_6_sol_luna_costs, 20260923_000000_pin_claude_opus_5_5_full_model
Create Date: 2026-09-23
"""

from __future__ import annotations

revision = "20260923_010000_merge_gpt_6_sol_luna_and_opus_5_5_heads"
down_revision = (
    "20260922_000000_backfill_gpt_6_sol_luna_costs",
    "20260923_000000_pin_claude_opus_5_5_full_model",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    return None


def downgrade() -> None:
    return None
