"""merge ollama sidecar and dashboard guest heads

Revision ID: 20260619_020000_merge_ollama_and_guest_heads
Revises:
- 20260611_000000_merge_dashboard_guest_and_weekly_useragent_heads
- 20260619_013000_add_ollama_sidecar_dashboard_settings
Create Date: 2026-06-19 02:00:00.000000
"""

from __future__ import annotations

revision = "20260619_020000_merge_ollama_and_guest_heads"
down_revision = (
    "20260611_000000_merge_dashboard_guest_and_weekly_useragent_heads",
    "20260619_013000_add_ollama_sidecar_dashboard_settings",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
