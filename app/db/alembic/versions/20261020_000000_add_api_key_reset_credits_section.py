"""decide whether existing API keys keep self-service reset credits

``/v1/reset-credit`` now needs the ``reset_credits`` usage section. Before
this revision every API key could list the reset credits (with account
emails) of its account pool and redeem them; new keys are created without
the section.

``GRANT_RESET_CREDITS_TO_EXISTING_KEYS`` decides what existing keys get:

- ``False`` (the default): existing keys lose reset-credit access like new
  keys. An admin re-enables it per key in the dashboard. Nothing is written.
- ``True``: every existing key gets ``reset_credits`` added to its usage
  sections and keeps today's access.

Revision ID: 20261020_000000_add_api_key_reset_credits_section
Revises: 20261019_000000_add_request_log_cache_write_tokens
Create Date: 2026-10-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20261020_000000_add_api_key_reset_credits_section"
down_revision = "20261019_000000_add_request_log_cache_write_tokens"
branch_labels = None
depends_on = None

GRANT_RESET_CREDITS_TO_EXISTING_KEYS = False

_TABLE = "api_keys"
_SECTION = "reset_credits"
_BATCH_SIZE = 250


def _sections(raw: str | None) -> list[str]:
    if raw is None:
        return []
    return [section.strip() for section in raw.split(",") if section.strip()]


def _has_usage_sections(connection: Connection) -> bool:
    inspector = sa.inspect(connection)
    if not inspector.has_table(_TABLE):
        return False
    columns = {str(column["name"]) for column in inspector.get_columns(_TABLE) if column.get("name") is not None}
    return "usage_sections" in columns


def grant_reset_credits_to_existing_keys(connection: Connection) -> None:
    """Add ``reset_credits`` to every key, in bounded keyset batches."""

    if not _has_usage_sections(connection):
        return
    last_id: str | None = None
    while True:
        after = "" if last_id is None else "WHERE id > :last_id "
        batch = connection.execute(
            sa.text(f"SELECT id, usage_sections FROM {_TABLE} {after}ORDER BY id LIMIT :limit"),
            {"last_id": last_id, "limit": _BATCH_SIZE},
        ).fetchall()
        for key_id, raw in batch:
            sections = _sections(raw)
            if _SECTION not in sections:
                connection.execute(
                    sa.text(f"UPDATE {_TABLE} SET usage_sections = :sections WHERE id = :id"),
                    {"sections": ",".join([*sections, _SECTION]), "id": key_id},
                )
        if len(batch) < _BATCH_SIZE:
            return
        last_id = str(batch[-1][0])


def upgrade() -> None:
    if GRANT_RESET_CREDITS_TO_EXISTING_KEYS:
        grant_reset_credits_to_existing_keys(op.get_bind())


def downgrade() -> None:
    """Keep ``reset_credits`` on every key.

    Nothing records which grants this revision wrote, and an admin may have
    granted the section after the upgrade, so removing it could destroy a
    choice this revision never made. Older code ignores the section when it
    decides access (every key can use reset credits there), and a re-upgrade
    finds every grant intact. One older-code caveat: its edit dialog sends a
    key's stored sections back unchanged and its service rejects unknown
    ones, so saving such a key fails until the admin toggles any usage
    section, which makes the older picker send only the sections it knows.
    """
