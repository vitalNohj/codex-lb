"""alias pools: normalize alias values, add request-log pool columns

Revision ID: 20260923_020000_add_alias_pool_failover
Revises: 20260923_010000_merge_gpt_6_sol_luna_and_opus_5_5_heads
Create Date: 2026-09-23 00:00:00.000000

``dashboard_settings.model_aliases_json`` moves from ``{alias: "model"}`` to
``{alias: {"targets": ["model", ...]}}``. The column is neither renamed nor
retyped; only the value shape changes. ``request_logs`` gains
``upstream_model`` (the pool target that served an alias request) and
``pool_attempts`` (how many targets were tried), both nullable and null for
every non-pool request.
"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20260923_020000_add_alias_pool_failover"
down_revision = "20260923_010000_merge_gpt_6_sol_luna_and_opus_5_5_heads"
branch_labels = None
depends_on = None

_SETTINGS_TABLE = "dashboard_settings"
_ALIASES_COLUMN = "model_aliases_json"
_LOGS_TABLE = "request_logs"
_UPSTREAM_MODEL_COLUMN = "upstream_model"
_POOL_ATTEMPTS_COLUMN = "pool_attempts"


def _columns(connection: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name) if column.get("name") is not None}


def _load_alias_map(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _normalize_targets(raw_targets: list[Any]) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()
    for target in raw_targets:
        if not isinstance(target, str):
            continue
        normalized = target.strip()
        if not normalized or normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        targets.append(normalized)
    return targets


def _to_pool_shape(raw: Any) -> str | None:
    """Rewrite string values to one-target pools; ``None`` when nothing changes."""

    parsed = _load_alias_map(raw)
    if parsed is None:
        return None
    changed = False
    pools: dict[str, dict[str, list[str]]] = {}
    for alias, value in parsed.items():
        if not isinstance(alias, str) or not alias.strip():
            changed = True
            continue
        if isinstance(value, str):
            targets = _normalize_targets([value])
            changed = True
        elif isinstance(value, dict) and isinstance(value.get("targets"), list):
            targets = _normalize_targets(value["targets"])
            if targets != value["targets"] or set(value) != {"targets"}:
                changed = True
        else:
            changed = True
            continue
        if not targets:
            changed = True
            continue
        pools[alias.strip()] = {"targets": targets}
    if not changed:
        return None
    return json.dumps(pools, sort_keys=True, separators=(",", ":"))


def _to_legacy_shape(raw: Any) -> str | None:
    """Rewrite pools to their first target as a string; ``None`` when nothing changes."""

    parsed = _load_alias_map(raw)
    if parsed is None:
        return None
    changed = False
    aliases: dict[str, str] = {}
    for alias, value in parsed.items():
        if not isinstance(alias, str) or not alias.strip():
            changed = True
            continue
        if isinstance(value, str):
            if value.strip():
                aliases[alias.strip()] = value.strip()
            else:
                changed = True
            continue
        if isinstance(value, dict) and isinstance(value.get("targets"), list):
            targets = _normalize_targets(value["targets"])
            changed = True
            if targets:
                aliases[alias.strip()] = targets[0]
            continue
        changed = True
    if not changed:
        return None
    return json.dumps(aliases, sort_keys=True, separators=(",", ":"))


def _rewrite_alias_rows(bind: Connection, rewrite: Any) -> None:
    if _ALIASES_COLUMN not in _columns(bind, _SETTINGS_TABLE):
        return
    rows = bind.execute(sa.text(f"SELECT id, {_ALIASES_COLUMN} FROM {_SETTINGS_TABLE}")).mappings().all()
    for row in rows:
        rewritten = rewrite(row[_ALIASES_COLUMN])
        if rewritten is None:
            continue
        bind.execute(
            sa.text(f"UPDATE {_SETTINGS_TABLE} SET {_ALIASES_COLUMN} = :aliases WHERE id = :id"),
            {"id": row["id"], "aliases": rewritten},
        )


def upgrade() -> None:
    bind = op.get_bind()
    _rewrite_alias_rows(bind, _to_pool_shape)

    log_columns = _columns(bind, _LOGS_TABLE)
    if not log_columns:
        return
    missing_upstream = _UPSTREAM_MODEL_COLUMN not in log_columns
    missing_attempts = _POOL_ATTEMPTS_COLUMN not in log_columns
    if not missing_upstream and not missing_attempts:
        return
    with op.batch_alter_table(_LOGS_TABLE) as batch_op:
        if missing_upstream:
            batch_op.add_column(sa.Column(_UPSTREAM_MODEL_COLUMN, sa.String(), nullable=True))
        if missing_attempts:
            batch_op.add_column(sa.Column(_POOL_ATTEMPTS_COLUMN, sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    log_columns = _columns(bind, _LOGS_TABLE)
    present = [column for column in (_UPSTREAM_MODEL_COLUMN, _POOL_ATTEMPTS_COLUMN) if column in log_columns]
    if present:
        with op.batch_alter_table(_LOGS_TABLE) as batch_op:
            for column in present:
                batch_op.drop_column(column)

    _rewrite_alias_rows(bind, _to_legacy_shape)
