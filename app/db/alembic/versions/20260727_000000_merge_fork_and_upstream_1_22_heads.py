"""merge fork head with upstream v1.22.0 migration heads

Revision ID: 20260727_000000_merge_fork_and_upstream_1_22_heads
Revises: 20260717_000000_merge_fork_upstream_heads, 20260722_000000_backfill_request_log_useragent_families
Create Date: 2026-07-27
"""

from __future__ import annotations

revision = "20260727_000000_merge_fork_and_upstream_1_22_heads"
down_revision = (
    "20260717_000000_merge_fork_upstream_heads",
    "20260722_000000_backfill_request_log_useragent_families",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    return


def downgrade() -> None:
    return
