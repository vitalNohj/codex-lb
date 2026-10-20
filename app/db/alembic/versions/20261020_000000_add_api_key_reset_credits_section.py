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

from collections.abc import Callable

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


def _rewrite_sections(connection: Connection, transform: Callable[[list[str]], list[str] | None]) -> None:
    """Apply ``transform`` to every key's sections, in bounded keyset batches.

    ``transform`` returns the new sections, or ``None`` to leave the key alone.
    """

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
            updated = transform(_sections(raw))
            if updated is not None:
                connection.execute(
                    sa.text(f"UPDATE {_TABLE} SET usage_sections = :sections WHERE id = :id"),
                    {"sections": ",".join(updated), "id": key_id},
                )
        if len(batch) < _BATCH_SIZE:
            return
        last_id = str(batch[-1][0])


def _with_section(sections: list[str]) -> list[str] | None:
    return None if _SECTION in sections else [*sections, _SECTION]


def _without_section(sections: list[str]) -> list[str] | None:
    return [section for section in sections if section != _SECTION] if _SECTION in sections else None


def grant_reset_credits_to_existing_keys(connection: Connection) -> None:
    _rewrite_sections(connection, _with_section)


def upgrade() -> None:
    if GRANT_RESET_CREDITS_TO_EXISTING_KEYS:
        grant_reset_credits_to_existing_keys(op.get_bind())


def downgrade() -> None:
    """Remove the section older code does not know.

    The older dashboard edit dialog sends a key's stored sections back on
    every save, and the older service rejects an unknown section, so a key
    that kept ``reset_credits`` could no longer be edited after a downgrade.
    Removing it drops nothing that code can act on: before this revision
    every key could use reset credits. A later re-upgrade starts from the
    same choice as a fresh upgrade.
    """

    _rewrite_sections(op.get_bind(), _without_section)
