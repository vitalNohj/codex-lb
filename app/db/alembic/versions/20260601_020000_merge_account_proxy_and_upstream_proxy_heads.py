"""merge account proxy and upstream proxy routing heads

Revision ID: 20260601_020000_merge_account_proxy_and_upstream_proxy_heads
Revises: 20260523_000000_add_accounts_proxy_columns, 20260601_010000_add_upstream_proxy_routing
Create Date: 2026-06-01 20:00:00.000000
"""

from __future__ import annotations

revision = "20260601_020000_merge_account_proxy_and_upstream_proxy_heads"
down_revision = (
    "20260523_000000_add_accounts_proxy_columns",
    "20260601_010000_add_upstream_proxy_routing",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
