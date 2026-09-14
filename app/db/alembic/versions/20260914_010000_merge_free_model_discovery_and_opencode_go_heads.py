"""merge the free-model-discovery and OpenCode Go sidecar migration heads

Revision ID: 20260914_010000_merge_free_model_discovery_and_opencode_go_heads
Revises: 20260911_000000_add_free_model_discovery, 20260914_000000_add_opencode_go_sidecar_dashboard_settings
Create Date: 2026-09-14

Both parents were authored against the same Astra-backfill parent on separate
branches - free-model discovery in the production checkout, the OpenCode Go
sidecar settings on main - so reconciling them leaves Alembic with two heads.

This is an empty merge point, the same convention the fork/upstream merge
revision already uses. Neither parent is rewritten or re-parented: both may
already be applied on a running deployment, and re-parenting an applied
revision would desynchronize alembic_version from the real schema. No table or
column is created, altered or dropped here.
"""

from __future__ import annotations

revision = "20260914_010000_merge_free_model_discovery_and_opencode_go_heads"
down_revision = (
    "20260911_000000_add_free_model_discovery",
    "20260914_000000_add_opencode_go_sidecar_dashboard_settings",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    return


def downgrade() -> None:
    return
