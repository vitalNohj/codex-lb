"""fold the NVIDIA sidecar into the OpenAI-compat endpoint list

Revision ID: 20260925_000000_fold_nvidia_into_openai_compat
Revises: 20260923_010000_merge_gpt_6_sol_luna_and_opus_5_5_heads
Create Date: 2026-09-25 00:00:00.000000

The NVIDIA integration was a verbatim clone of a generic OpenAI-compatible
endpoint. This revision copies any configured NVIDIA settings into one entry of
``openai_compat_endpoints_json`` (named ``NVIDIA``), repoints its request-log
rows, and drops the dedicated columns.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20260925_000000_fold_nvidia_into_openai_compat"
down_revision = "20260923_010000_merge_gpt_6_sol_luna_and_opus_5_5_heads"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

_TABLE_NAME = "dashboard_settings"
_ENDPOINTS_COLUMN = "openai_compat_endpoints_json"
_LEGACY_LOG_SOURCE = "nvidia_sidecar"
_DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
_FOLDED_NAME = "NVIDIA"
_MAX_ENDPOINTS = 32


def _nvidia_columns() -> tuple[sa.Column[Any], ...]:
    """Fresh Column objects each call: a Column can only be bound to one table."""

    return (
        sa.Column("nvidia_sidecar_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "nvidia_sidecar_base_url",
            sa.String(),
            server_default=sa.text(f"'{_DEFAULT_BASE_URL}'"),
            nullable=False,
        ),
        sa.Column("nvidia_sidecar_api_key_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("nvidia_sidecar_model_prefixes_json", sa.Text(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("nvidia_sidecar_full_models_json", sa.Text(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("nvidia_sidecar_connect_timeout_seconds", sa.Float(), server_default=sa.text("8.0"), nullable=False),
        sa.Column(
            "nvidia_sidecar_request_timeout_seconds", sa.Float(), server_default=sa.text("600.0"), nullable=False
        ),
        sa.Column(
            "nvidia_sidecar_models_cache_ttl_seconds", sa.Float(), server_default=sa.text("60.0"), nullable=False
        ),
        sa.Column("nvidia_sidecar_last_health_status", sa.String(), nullable=True),
        sa.Column("nvidia_sidecar_last_health_message", sa.Text(), nullable=True),
        sa.Column("nvidia_sidecar_last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("nvidia_sidecar_last_model_count", sa.Integer(), nullable=True),
        sa.Column("nvidia_sidecar_default_reasoning_effort", sa.String(), nullable=True),
    )


_NVIDIA_COLUMN_NAMES = tuple(column.name for column in _nvidia_columns())


def _columns(connection: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name) if column.get("name") is not None}


def _load_json_list(raw: object) -> list[Any]:
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _is_configured(row: sa.Row[Any]) -> bool:
    """A row counts as configured when the operator changed anything from the defaults."""

    if row.nvidia_sidecar_api_key_encrypted:
        return True
    if bool(row.nvidia_sidecar_enabled):
        return True
    base_url = (row.nvidia_sidecar_base_url or "").rstrip("/")
    if base_url and base_url != _DEFAULT_BASE_URL:
        return True
    if _load_json_list(row.nvidia_sidecar_model_prefixes_json):
        return True
    return bool(_load_json_list(row.nvidia_sidecar_full_models_json))


def _unique_name(existing: list[dict[str, Any]]) -> str:
    taken = {str(entry.get("name", "")).strip().casefold() for entry in existing if isinstance(entry, dict)}
    if _FOLDED_NAME.casefold() not in taken:
        return _FOLDED_NAME
    suffix = 2
    while f"{_FOLDED_NAME} ({suffix})".casefold() in taken:
        suffix += 1
    return f"{_FOLDED_NAME} ({suffix})"


def _folded_entry(row: sa.Row[Any], existing: list[dict[str, Any]]) -> dict[str, Any]:
    # The OpenAI-compat list stores base64(fernet bytes); the NVIDIA column
    # stored the raw fernet bytes under the same TokenEncryptor, so re-encoding
    # is enough and nothing is decrypted here.
    ciphertext = row.nvidia_sidecar_api_key_encrypted
    encrypted_b64 = base64.b64encode(bytes(ciphertext)).decode("ascii") if ciphertext else None
    return {
        "id": str(uuid4()),
        "name": _unique_name(existing),
        "enabled": bool(row.nvidia_sidecar_enabled),
        "base_url": (row.nvidia_sidecar_base_url or _DEFAULT_BASE_URL).rstrip("/") or _DEFAULT_BASE_URL,
        "api_key_encrypted": encrypted_b64,
        "model_prefixes": _load_json_list(row.nvidia_sidecar_model_prefixes_json),
        "full_models": _load_json_list(row.nvidia_sidecar_full_models_json),
        "connect_timeout_seconds": float(row.nvidia_sidecar_connect_timeout_seconds or 8.0),
        "request_timeout_seconds": float(row.nvidia_sidecar_request_timeout_seconds or 600.0),
        "models_cache_ttl_seconds": float(
            row.nvidia_sidecar_models_cache_ttl_seconds
            if row.nvidia_sidecar_models_cache_ttl_seconds is not None
            else 60.0
        ),
        "default_reasoning_effort": row.nvidia_sidecar_default_reasoning_effort or None,
        "last_health_status": None,
        "last_health_message": None,
        "last_checked_at": None,
        "last_model_count": None,
    }


def _fold(bind: Connection, columns: set[str]) -> None:
    if _ENDPOINTS_COLUMN not in columns:
        logger.warning("nvidia fold: %s missing; dropping NVIDIA columns without folding", _ENDPOINTS_COLUMN)
        return
    select_columns = ", ".join((*_NVIDIA_COLUMN_NAMES, _ENDPOINTS_COLUMN))
    row = bind.execute(sa.text(f"SELECT {select_columns} FROM {_TABLE_NAME} WHERE id = 1")).first()
    if row is None or not _is_configured(row):
        return
    existing = _load_json_list(getattr(row, _ENDPOINTS_COLUMN))
    if len(existing) >= _MAX_ENDPOINTS:
        logger.warning(
            "nvidia fold: %s already holds %d endpoints; NVIDIA settings were not migrated",
            _ENDPOINTS_COLUMN,
            len(existing),
        )
        return
    entry = _folded_entry(row, existing)
    bind.execute(
        sa.text(f"UPDATE {_TABLE_NAME} SET {_ENDPOINTS_COLUMN} = :value WHERE id = 1"),
        {"value": json.dumps([*existing, entry], separators=(",", ":"))},
    )
    if sa.inspect(bind).has_table("request_logs"):
        bind.execute(
            sa.text("UPDATE request_logs SET source = :new_source WHERE source = :old_source"),
            {"new_source": f"openai_compat:{entry['id']}", "old_source": _LEGACY_LOG_SOURCE},
        )


def upgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, _TABLE_NAME)
    present = [name for name in _NVIDIA_COLUMN_NAMES if name in columns]
    if not present:
        return
    if set(present) == set(_NVIDIA_COLUMN_NAMES):
        _fold(bind, columns)
    else:
        logger.warning("nvidia fold: partial NVIDIA column set %s; dropping without folding", present)
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        for name in present:
            batch_op.drop_column(name)


def downgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, _TABLE_NAME)
    if not columns:
        return
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        for column in _nvidia_columns():
            if column.name not in columns:
                batch_op.add_column(column)
