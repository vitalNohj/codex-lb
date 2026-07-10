"""merge custom alias catalog and ttft observability heads

Revision ID: 20260710_000000_merge_alias_catalog_and_ttft_heads
Revises: 20260706_000000_add_custom_alias_catalog, 20260709_000000_add_ttft_phase_observability
Create Date: 2026-07-10
"""

from __future__ import annotations

revision = "20260710_000000_merge_alias_catalog_and_ttft_heads"
down_revision = (
    "20260706_000000_add_custom_alias_catalog",
    "20260709_000000_add_ttft_phase_observability",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    return


def downgrade() -> None:
    return
