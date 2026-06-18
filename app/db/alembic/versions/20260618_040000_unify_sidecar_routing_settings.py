"""unify sidecar routing settings

Revision ID: 20260618_040000_unify_sidecar_routing_settings
Revises: 20260614_020000_add_request_log_reference_cost
Create Date: 2026-06-18 04:00:00.000000
"""

from __future__ import annotations

import json
import logging

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20260618_040000_unify_sidecar_routing_settings"
down_revision = "20260614_020000_add_request_log_reference_cost"
branch_labels = None
depends_on = None

_TABLE_NAME = "dashboard_settings"
_DEFAULT_CLAUDE_PREFIXES = (
    {"prefix": "claude", "strip": False},
    {"prefix": "cp-", "strip": True},
    {"prefix": "cp_", "strip": True},
)

logger = logging.getLogger(__name__)


def _columns(connection: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name) if column.get("name") is not None}


def _load_json_list(raw: str | None) -> list[object]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _normalize_prefix_rows(raw: str | None, *, seed_claude_aliases: bool = False) -> str:
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for entry in _load_json_list(raw):
        if isinstance(entry, str):
            prefix = entry.strip().lower()
            strip = prefix.endswith(("-", "_"))
        elif isinstance(entry, dict):
            value = entry.get("prefix")
            if not isinstance(value, str):
                continue
            prefix = value.strip().lower()
            strip = bool(entry.get("strip", prefix.endswith(("-", "_"))))
        else:
            continue
        if not prefix or prefix in seen:
            continue
        seen.add(prefix)
        rows.append({"prefix": prefix, "strip": strip})

    if seed_claude_aliases:
        for row in _DEFAULT_CLAUDE_PREFIXES:
            prefix = str(row["prefix"])
            if prefix not in seen:
                seen.add(prefix)
                rows.append(dict(row))

    return json.dumps(rows, sort_keys=True, separators=(",", ":"))


def _collapse_prefix_rows(raw: str | None) -> str:
    prefixes: list[str] = []
    seen: set[str] = set()
    for entry in _load_json_list(raw):
        if isinstance(entry, str):
            prefix = entry.strip().lower()
        elif isinstance(entry, dict):
            value = entry.get("prefix")
            prefix = value.strip().lower() if isinstance(value, str) else ""
        else:
            continue
        if not prefix or prefix in seen:
            continue
        seen.add(prefix)
        prefixes.append(prefix)
    return json.dumps(prefixes, separators=(",", ":"))


def _log_cross_integration_prefix_collisions(connection: Connection) -> None:
    columns = _columns(connection, _TABLE_NAME)
    if not columns or "id" not in columns:
        return
    prefix_columns = [
        ("CLIProxyAPI", "claude_sidecar_model_prefixes_json"),
        ("OpenRouter", "openrouter_sidecar_model_prefixes_json"),
        ("OmniRoute", "omniroute_sidecar_prefixes_json"),
    ]
    present = [(name, column) for name, column in prefix_columns if column in columns]
    if len(present) < 2:
        return
    selected_columns = ", ".join(f"{column} AS {column}" for _, column in present)
    for row in connection.execute(sa.text(f"SELECT id, {selected_columns} FROM {_TABLE_NAME}")).mappings():
        owners: dict[str, str] = {}
        for provider, column in present:
            for entry in _load_json_list(row[column]):
                prefix = ""
                if isinstance(entry, str):
                    prefix = entry.strip().lower()
                elif isinstance(entry, dict) and isinstance(entry.get("prefix"), str):
                    prefix = str(entry["prefix"]).strip().lower()
                if not prefix:
                    continue
                owner = owners.get(prefix)
                if owner is not None and owner != provider:
                    logger.warning(
                        "dashboard_settings row %s has sidecar prefix collision for %r between %s and %s",
                        row["id"],
                        prefix,
                        owner,
                        provider,
                    )
                owners[prefix] = provider


def upgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, _TABLE_NAME)
    if not columns:
        return

    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        if "claude_sidecar_model_prefixes_json" in columns:
            batch_op.alter_column(
                "claude_sidecar_model_prefixes_json",
                server_default=sa.text("'[]'"),
                existing_type=sa.Text(),
            )
        if "openrouter_sidecar_model_prefixes_json" in columns:
            batch_op.alter_column(
                "openrouter_sidecar_model_prefixes_json",
                server_default=sa.text("'[]'"),
                existing_type=sa.Text(),
            )

        if "claude_sidecar_full_models_json" not in columns:
            batch_op.add_column(
                sa.Column("claude_sidecar_full_models_json", sa.Text(), server_default=sa.text("'[]'"), nullable=False)
            )
        if "openrouter_sidecar_full_models_json" not in columns:
            batch_op.add_column(
                sa.Column(
                    "openrouter_sidecar_full_models_json",
                    sa.Text(),
                    server_default=sa.text("'[]'"),
                    nullable=False,
                )
            )
        if "omniroute_sidecar_prefixes_json" not in columns:
            batch_op.add_column(
                sa.Column("omniroute_sidecar_prefixes_json", sa.Text(), server_default=sa.text("'[]'"), nullable=False)
            )

    columns = _columns(bind, _TABLE_NAME)
    if "claude_sidecar_model_prefixes_json" in columns:
        for row in bind.execute(
            sa.text(f"SELECT id, claude_sidecar_model_prefixes_json FROM {_TABLE_NAME}")
        ).mappings():
            bind.execute(
                sa.text(
                    f"UPDATE {_TABLE_NAME} "
                    "SET claude_sidecar_model_prefixes_json = :prefixes "
                    "WHERE id = :id"
                ),
                {
                    "id": row["id"],
                    "prefixes": _normalize_prefix_rows(
                        row["claude_sidecar_model_prefixes_json"],
                        seed_claude_aliases=True,
                    ),
                },
            )
    if "openrouter_sidecar_model_prefixes_json" in columns:
        for row in bind.execute(
            sa.text(f"SELECT id, openrouter_sidecar_model_prefixes_json FROM {_TABLE_NAME}")
        ).mappings():
            bind.execute(
                sa.text(
                    f"UPDATE {_TABLE_NAME} "
                    "SET openrouter_sidecar_model_prefixes_json = :prefixes "
                    "WHERE id = :id"
                ),
                {
                    "id": row["id"],
                    "prefixes": _normalize_prefix_rows(row["openrouter_sidecar_model_prefixes_json"]),
                },
            )
    if "omniroute_sidecar_prefixes_json" in columns:
        for row in bind.execute(sa.text(f"SELECT id, omniroute_sidecar_prefixes_json FROM {_TABLE_NAME}")).mappings():
            bind.execute(
                sa.text(f"UPDATE {_TABLE_NAME} SET omniroute_sidecar_prefixes_json = :prefixes WHERE id = :id"),
                {"id": row["id"], "prefixes": _normalize_prefix_rows(row["omniroute_sidecar_prefixes_json"])},
            )

    _log_cross_integration_prefix_collisions(bind)


def downgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, _TABLE_NAME)
    if not columns:
        return

    if "claude_sidecar_model_prefixes_json" in columns:
        for row in bind.execute(
            sa.text(f"SELECT id, claude_sidecar_model_prefixes_json FROM {_TABLE_NAME}")
        ).mappings():
            bind.execute(
                sa.text(
                    f"UPDATE {_TABLE_NAME} "
                    "SET claude_sidecar_model_prefixes_json = :prefixes "
                    "WHERE id = :id"
                ),
                {"id": row["id"], "prefixes": _collapse_prefix_rows(row["claude_sidecar_model_prefixes_json"])},
            )
    if "openrouter_sidecar_model_prefixes_json" in columns:
        for row in bind.execute(
            sa.text(f"SELECT id, openrouter_sidecar_model_prefixes_json FROM {_TABLE_NAME}")
        ).mappings():
            bind.execute(
                sa.text(
                    f"UPDATE {_TABLE_NAME} "
                    "SET openrouter_sidecar_model_prefixes_json = :prefixes "
                    "WHERE id = :id"
                ),
                {"id": row["id"], "prefixes": _collapse_prefix_rows(row["openrouter_sidecar_model_prefixes_json"])},
            )

    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        for column_name in (
            "omniroute_sidecar_prefixes_json",
            "openrouter_sidecar_full_models_json",
            "claude_sidecar_full_models_json",
        ):
            if column_name in columns:
                batch_op.drop_column(column_name)
