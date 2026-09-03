"""merge fork head with upstream v1.24.0 migration heads

Revision ID: 20260903_000000_merge_fork_and_upstream_1_24_heads
Revises: 20260828_000000_add_external_model_prices, 20260816_000000_add_model_source_embeddings
Create Date: 2026-09-03
"""

from __future__ import annotations

revision = "20260903_000000_merge_fork_and_upstream_1_24_heads"
down_revision = (
    "20260828_000000_add_external_model_prices",
    "20260816_000000_add_model_source_embeddings",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    return


def downgrade() -> None:
    return
