from __future__ import annotations

import json
from importlib import import_module

import pytest

migration = import_module(
    "app.db.alembic.versions.20260618_040000_unify_sidecar_routing_settings"
)

pytestmark = pytest.mark.unit


def test_upgrade_prefix_normalization_converts_strings_and_seeds_cli_aliases() -> None:
    upgraded = migration._normalize_prefix_rows(json.dumps(["Claude", "cp-", "cp-"]), seed_claude_aliases=True)

    assert json.loads(upgraded) == [
        {"prefix": "claude", "strip": False},
        {"prefix": "cp-", "strip": True},
        {"prefix": "cp_", "strip": True},
    ]


def test_upgrade_prefix_normalization_preserves_object_strip_flags() -> None:
    upgraded = migration._normalize_prefix_rows(
        json.dumps(
            [
                {"prefix": "or-", "strip": False},
                {"prefix": "OpenRouter/", "strip": True},
            ]
        )
    )

    assert json.loads(upgraded) == [
        {"prefix": "or-", "strip": False},
        {"prefix": "openrouter/", "strip": True},
    ]


def test_downgrade_prefix_collapse_returns_string_arrays() -> None:
    downgraded = migration._collapse_prefix_rows(
        json.dumps(
            [
                {"prefix": "claude", "strip": False},
                {"prefix": "cp-", "strip": True},
                "legacy/",
            ]
        )
    )

    assert json.loads(downgraded) == ["claude", "cp-", "legacy/"]
