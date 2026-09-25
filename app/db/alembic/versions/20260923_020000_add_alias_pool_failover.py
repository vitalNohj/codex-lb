"""alias pools: normalize alias values, add request-log pool columns

Revision ID: 20260923_020000_add_alias_pool_failover
Revises: 20260923_010000_merge_gpt_6_sol_luna_and_opus_5_5_heads
Create Date: 2026-09-23 00:00:00.000000

``dashboard_settings.model_aliases_json`` gains one value shape,
``{alias: {"targets": ["model", ...]}}``, used only for an alias with fallback
targets. A single-target alias stays ``{alias: "model"}``, so a replica still on
the previous release keeps reading - and, on its next settings save, keeping -
every alias that existed before the upgrade. Both directions therefore write
the same canonical form: a one-target object, if a row holds one, becomes its
string, and strings are left untouched. ``request_logs`` gains
``upstream_model`` (the pool target that served an alias request) and
``pool_attempts`` (how many targets were tried), both nullable and null for
every non-pool request.

Downgrade refuses, changing nothing, while an alias has fallback targets: the
legacy shape holds one target per alias, and truncating a pool would discard
targets an operator added after the upgrade, which this migration did not
write.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
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
# Settings rows are read and rewritten this many at a time. The table holds a
# single row today; the bound keeps the migration safe if that ever changes.
_BATCH_SIZE = 100
# How many aliases a refused downgrade names before summarizing the rest.
_MAX_NAMED_ALIASES = 10

_settings_table = sa.table(
    _SETTINGS_TABLE,
    sa.column("id", sa.Integer()),
    sa.column(_ALIASES_COLUMN, sa.Text()),
)


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


def _pool_targets(value: Any) -> list[str] | None:
    """A pool object's usable targets; ``None`` for anything else."""

    if isinstance(value, dict) and isinstance(value.get("targets"), list):
        return _normalize_targets(value["targets"])
    return None


def _fallback_aliases(raw: Any) -> list[str]:
    """Aliases with more than one target, which the legacy shape cannot hold."""

    parsed = _load_alias_map(raw)
    if parsed is None:
        return []
    return [alias.strip() for alias, value in parsed.items() if alias.strip() and len(_pool_targets(value) or ()) > 1]


def _to_legacy_shape(raw: Any) -> str | None:
    """Rewrite one-target pools to the string the previous version reads.

    ``None`` when nothing changes. Every other entry stays as it is: strings
    already have the legacy shape, a pool with fallback targets has no string
    form, and the previous version skips anything else. Both directions use
    this rewrite; ``downgrade`` additionally refuses while a pool exists.
    """

    parsed = _load_alias_map(raw)
    if parsed is None:
        return None
    changed = False
    aliases: dict[str, Any] = {}
    for alias, value in parsed.items():
        targets = _pool_targets(value)
        if targets is not None and len(targets) == 1:
            aliases[alias] = targets[0]
            changed = True
        else:
            aliases[alias] = value
    if not changed:
        return None
    return json.dumps(aliases, sort_keys=True, separators=(",", ":"))


def _alias_row_batches(bind: Connection) -> Iterator[list[tuple[Any, Any]]]:
    """Settings rows as ``(id, aliases)``, in id order, ``_BATCH_SIZE`` at a time."""

    id_column = _settings_table.c.id
    query = sa.select(id_column, _settings_table.c[_ALIASES_COLUMN]).order_by(id_column).limit(_BATCH_SIZE)
    last_id: Any = None
    while True:
        page = query if last_id is None else query.where(id_column > last_id)
        batch = [(row[0], row[1]) for row in bind.execute(page)]
        if not batch:
            return
        yield batch
        last_id = batch[-1][0]


def _rewrite_alias_rows(bind: Connection, rewrite: Callable[[Any], str | None]) -> None:
    if _ALIASES_COLUMN not in _columns(bind, _SETTINGS_TABLE):
        return
    update = (
        sa.update(_settings_table)
        .where(_settings_table.c.id == sa.bindparam("row_id"))
        .values({_ALIASES_COLUMN: sa.bindparam("aliases")})
    )
    for batch in _alias_row_batches(bind):
        changes = [
            {"row_id": row_id, "aliases": rewritten} for row_id, raw in batch if (rewritten := rewrite(raw)) is not None
        ]
        if changes:
            bind.execute(update, changes)


def _aliases_blocking_downgrade(bind: Connection) -> tuple[list[str], int]:
    """The first ``_MAX_NAMED_ALIASES`` aliases that block a downgrade, and how many there are.

    Only the names the refusal message prints are kept, so memory stays bounded
    by a batch no matter how many rows or aliases there are.
    """

    if _ALIASES_COLUMN not in _columns(bind, _SETTINGS_TABLE):
        return [], 0
    named: list[str] = []
    count = 0
    for batch in _alias_row_batches(bind):
        for _row_id, raw in batch:
            for alias in _fallback_aliases(raw):
                count += 1
                if len(named) < _MAX_NAMED_ALIASES:
                    named.append(alias)
    return named, count


def _downgrade_refusal(named_aliases: list[str], count: int) -> str:
    named = ", ".join(f"'{alias}'" for alias in named_aliases)
    if count > len(named_aliases):
        named += f" and {count - len(named_aliases)} more"
    if count == 1:
        subject, reduce = f"alias {named} has", "Reduce it"
    else:
        subject, reduce = f"aliases {named} have", "Reduce each"
    return (
        f"cannot downgrade {revision}: {subject} fallback targets, which the previous version "
        f"cannot store. {reduce} to the one target it should keep (Settings > Advanced settings > "
        "Routing > Model aliasing), then run the downgrade again."
    )


def upgrade() -> None:
    bind = op.get_bind()
    _rewrite_alias_rows(bind, _to_legacy_shape)

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
    # Refuse before changing anything; see the module docstring.
    named, count = _aliases_blocking_downgrade(bind)
    if count:
        raise RuntimeError(_downgrade_refusal(named, count))

    log_columns = _columns(bind, _LOGS_TABLE)
    present = [column for column in (_UPSTREAM_MODEL_COLUMN, _POOL_ATTEMPTS_COLUMN) if column in log_columns]
    if present:
        with op.batch_alter_table(_LOGS_TABLE) as batch_op:
            for column in present:
                batch_op.drop_column(column)

    _rewrite_alias_rows(bind, _to_legacy_shape)
