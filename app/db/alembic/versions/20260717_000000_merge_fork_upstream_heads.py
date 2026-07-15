"""merge fork routing/integration and upstream heads

Revision ID: 20260717_000000_merge_fork_upstream_heads
Revises: 20260710_000000_merge_alias_catalog_and_ttft_heads, 20260716_000000_add_oauth_device_flow_slots
Create Date: 2026-07-17
"""

from __future__ import annotations

revision = "20260717_000000_merge_fork_upstream_heads"
down_revision = (
    "20260710_000000_merge_alias_catalog_and_ttft_heads",
    "20260716_000000_add_oauth_device_flow_slots",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    return


def downgrade() -> None:
    return
