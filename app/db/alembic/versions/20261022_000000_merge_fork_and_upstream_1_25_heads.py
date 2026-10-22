"""merge fork head with upstream v1.25 (main 72630bbfe) migration heads

Revision ID: 20261022_000000_merge_fork_and_upstream_1_25_heads
Revises: 20261021_010000_add_dashboard_layout, 20260918_000000_merge_scim_and_overflow_heads
Create Date: 2026-10-22
"""

from __future__ import annotations

revision = "20261022_000000_merge_fork_and_upstream_1_25_heads"
down_revision = (
    "20261021_010000_add_dashboard_layout",
    "20260918_000000_merge_scim_and_overflow_heads",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    return


def downgrade() -> None:
    return
