"""full-model stars: default-route integration per full model

Revision ID: 20261005_000000_add_full_model_stars
Revises: 20261003_010000_backfill_gpt_6_1_sol_costs
Create Date: 2026-10-05 00:00:00.000000

``dashboard_settings`` gains ``sidecar_full_model_stars_json``, a JSON object
mapping a lower-cased full model to the provider key of the integration that is
starred as the model's default route. The same full model may now be configured
on several integrations; the star names the card a bare full-model request
routes to.

Every existing full model becomes starred on its current card, so routing is
unchanged after the upgrade: before this revision the save-time uniqueness
check guaranteed at most one card per full model, so each model found in a
card's list maps to exactly that card. A model already starred (the column can
exist from a replayed legacy remap) keeps its star.
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20261005_000000_add_full_model_stars"
down_revision = "20261003_010000_backfill_gpt_6_1_sol_costs"
branch_labels = None
depends_on = None

_TABLE_NAME = "dashboard_settings"
_STARS_COLUMN = "sidecar_full_model_stars_json"

# Provider key -> the dashboard_settings column holding that integration's
# full-model JSON list. openai_compat endpoints live in their own JSON column
# and are handled separately.
_CARD_FULL_MODEL_COLUMNS: tuple[tuple[str, str], ...] = (
    ("claude", "claude_sidecar_full_models_json"),
    ("openrouter", "openrouter_sidecar_full_models_json"),
    ("orcarouter", "orcarouter_sidecar_full_models_json"),
    ("opencode_go", "opencode_go_sidecar_full_models_json"),
    ("omniroute", "omniroute_sidecar_full_models_json"),
    ("ollama", "ollama_sidecar_full_models_json"),
)


def _columns(connection: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name) if column.get("name") is not None}


def _load_str_list(raw: object) -> list[str]:
    """Strings from a JSON list column or an already-parsed list value."""

    if isinstance(raw, list):
        return [entry for entry in raw if isinstance(entry, str)]
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [entry for entry in parsed if isinstance(entry, str)]


def _load_star_map(raw: object) -> dict[str, str]:
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): str(value) for key, value in parsed.items() if isinstance(key, str) and isinstance(value, str)}


def _openai_compat_cards(raw: object) -> list[tuple[str, list[str]]]:
    """``(provider_key, full_models)`` per configured openai_compat endpoint."""

    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        endpoints = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(endpoints, list):
        return []
    cards: list[tuple[str, list[str]]] = []
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            continue
        endpoint_id = endpoint.get("id")
        if not isinstance(endpoint_id, str) or not endpoint_id.strip():
            continue
        models_json = endpoint.get("full_models")
        models = _load_str_list(models_json if isinstance(models_json, str) else None)
        cards.append((f"openai_compat:{endpoint_id.strip()}", models))
    return cards


def _seeded_stars(row: dict[str, object]) -> str | None:
    """The star map an unstarred row's full models imply, as JSON.

    ``None`` when the row needs no rewrite: the column is missing (handled by
    the caller), the map is unreadable, or it already names a star.
    """

    stars = _load_star_map(row.get(_STARS_COLUMN))
    if stars:
        return None
    seeded: dict[str, str] = {}
    for provider_key, column_name in _CARD_FULL_MODEL_COLUMNS:
        for model in _load_str_list(row.get(column_name)):
            normalized = model.strip().lower()
            if normalized:
                seeded.setdefault(normalized, provider_key)
    compat_column = "openai_compat_endpoints_json"
    if compat_column in row:
        for provider_key, models in _openai_compat_cards(row.get(compat_column)):
            for model in models:
                normalized = model.strip().lower()
                if normalized:
                    seeded.setdefault(normalized, provider_key)
    if not seeded:
        return None
    return json.dumps(seeded, sort_keys=True, separators=(",", ":"))


def upgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, _TABLE_NAME)
    if not columns:
        return
    if _STARS_COLUMN not in columns:
        with op.batch_alter_table(_TABLE_NAME) as batch_op:
            batch_op.add_column(sa.Column(_STARS_COLUMN, sa.Text(), nullable=False, server_default=sa.text("'{}'")))
    # Column names that are absent are skipped per row, so a partially migrated
    # schema still seeds what it can instead of failing outright.
    select_keys = ["id", _STARS_COLUMN, *{name for _, name in _CARD_FULL_MODEL_COLUMNS if name in columns}]
    if "openai_compat_endpoints_json" in columns:
        select_keys.append("openai_compat_endpoints_json")
    rows = bind.execute(sa.text(f"SELECT {', '.join(select_keys)} FROM {_TABLE_NAME}")).mappings()
    updates: list[dict[str, object]] = []
    for row in rows:
        seeded = _seeded_stars(dict(row))
        if seeded is not None:
            updates.append({"row_id": row["id"], "stars": seeded})
    if updates:
        bind.execute(
            sa.text(f"UPDATE {_TABLE_NAME} SET {_STARS_COLUMN} = :stars WHERE id = :row_id"),
            updates,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _STARS_COLUMN in _columns(bind, _TABLE_NAME):
        with op.batch_alter_table(_TABLE_NAME) as batch_op:
            batch_op.drop_column(_STARS_COLUMN)
