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


def _sections(raw: str | None) -> list[str]:
    if raw is None:
        return []
    return [section.strip() for section in raw.split(",") if section.strip()]


def _key_sections(connection: Connection) -> list[tuple[str, str | None]]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(_TABLE):
        return []
    columns = {str(column["name"]) for column in inspector.get_columns(_TABLE) if column.get("name") is not None}
    if "usage_sections" not in columns:
        return []
    rows = connection.execute(sa.text("SELECT id, usage_sections FROM api_keys")).fetchall()
    return [(str(row[0]), row[1]) for row in rows]


def _write_sections(connection: Connection, key_id: str, sections: list[str]) -> None:
    connection.execute(
        sa.text("UPDATE api_keys SET usage_sections = :sections WHERE id = :id"),
        {"sections": ",".join(sections), "id": key_id},
    )


def grant_reset_credits_to_existing_keys(connection: Connection) -> None:
    for key_id, raw in _key_sections(connection):
        sections = _sections(raw)
        if _SECTION not in sections:
            _write_sections(connection, key_id, [*sections, _SECTION])


def upgrade() -> None:
    if GRANT_RESET_CREDITS_TO_EXISTING_KEYS:
        grant_reset_credits_to_existing_keys(op.get_bind())


def downgrade() -> None:
    """Remove the section older code does not know.

    Older code rejects an unknown usage section when a key is saved, and it
    lets every key use reset credits anyway, so the grant has no meaning
    there.
    """

    connection = op.get_bind()
    for key_id, raw in _key_sections(connection):
        sections = _sections(raw)
        if _SECTION in sections:
            _write_sections(connection, key_id, [section for section in sections if section != _SECTION])
