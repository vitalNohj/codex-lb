from __future__ import annotations

import json
from importlib import import_module

import pytest

from app.modules.settings.model_alias_pools import (
    ModelAliasPool,
    alias_pools_to_plain,
    dump_alias_pools_json,
    find_alias_pool,
    normalize_alias_pools,
    parse_alias_pools_json,
    primary_targets,
)

migration = import_module("app.db.alembic.versions.20260923_020000_add_alias_pool_failover")

pytestmark = pytest.mark.unit


def test_parse_reads_pool_shape() -> None:
    pools = parse_alias_pools_json(json.dumps({"pooled/glm": {"targets": ["or/glm", "orca/glm"]}}))

    assert pools == {"pooled/glm": ModelAliasPool(targets=("or/glm", "orca/glm"))}
    assert pools["pooled/glm"].is_pool is True
    assert pools["pooled/glm"].primary == "or/glm"


def test_parse_reads_legacy_string_shape_as_single_target_pool() -> None:
    pools = parse_alias_pools_json(json.dumps({"custom_r1": " cc/claude "}))

    assert pools == {"custom_r1": ModelAliasPool(targets=("cc/claude",))}
    assert pools["custom_r1"].is_pool is False


def test_parse_accepts_mixed_shapes_during_rolling_upgrade() -> None:
    pools = parse_alias_pools_json(json.dumps({"a": "x", "b": {"targets": ["y", "z"]}}))

    assert primary_targets(pools) == {"a": "x", "b": "y"}


def test_parse_drops_blank_and_invalid_entries() -> None:
    raw = json.dumps(
        {
            " ": "x",
            "empty": {"targets": []},
            "blank-targets": {"targets": ["", "  "]},
            "not-a-list": {"targets": "x"},
            "number": 3,
            "ok": "y",
        }
    )

    assert parse_alias_pools_json(raw) == {"ok": ModelAliasPool(targets=("y",))}


def test_parse_dedupes_aliases_and_targets_case_insensitively_keeping_first() -> None:
    raw = json.dumps({"Alias": {"targets": ["A/b", "a/B", "c"]}, "alias": "ignored"})

    assert parse_alias_pools_json(raw) == {"Alias": ModelAliasPool(targets=("A/b", "c"))}


def test_parse_tolerates_garbage() -> None:
    assert parse_alias_pools_json(None) == {}
    assert parse_alias_pools_json("") == {}
    assert parse_alias_pools_json("not json") == {}
    assert parse_alias_pools_json("[1, 2]") == {}


def test_dump_writes_pool_shape_sorted_and_compact() -> None:
    dumped = dump_alias_pools_json({"b": ModelAliasPool(targets=("y",)), "a": "x"})

    assert dumped == '{"a":{"targets":["x"]},"b":{"targets":["y"]}}'
    assert parse_alias_pools_json(dumped) == normalize_alias_pools({"a": "x", "b": "y"})


def test_plain_shape_round_trips() -> None:
    pools = {"pooled/glm": ModelAliasPool(targets=("or/glm", "orca/glm"))}

    assert alias_pools_to_plain(pools) == {"pooled/glm": {"targets": ["or/glm", "orca/glm"]}}


def test_find_alias_pool_case_insensitive() -> None:
    pools = {"Pooled/GLM": ModelAliasPool(targets=("or/glm",))}

    assert find_alias_pool("pooled/glm", pools) == ("Pooled/GLM", pools["Pooled/GLM"])
    assert find_alias_pool("other", pools) is None
    assert find_alias_pool(None, pools) is None
    assert find_alias_pool("  ", pools) is None


def test_migration_upgrade_rewrites_legacy_strings_to_pools() -> None:
    upgraded = migration._to_pool_shape(json.dumps({"custom_r1": "cc/claude", "b": " x "}))

    assert upgraded is not None
    assert json.loads(upgraded) == {"b": {"targets": ["x"]}, "custom_r1": {"targets": ["cc/claude"]}}


def test_migration_upgrade_leaves_pool_shape_rows_untouched() -> None:
    assert migration._to_pool_shape(json.dumps({"a": {"targets": ["x", "y"]}})) is None
    assert migration._to_pool_shape("{}") is None
    assert migration._to_pool_shape(None) is None
    assert migration._to_pool_shape("not json") is None


def test_migration_upgrade_drops_unusable_entries() -> None:
    upgraded = migration._to_pool_shape(json.dumps({"a": "", "b": {"targets": []}, "c": 5, "d": "x"}))

    assert upgraded is not None
    assert json.loads(upgraded) == {"d": {"targets": ["x"]}}


def test_migration_downgrade_keeps_first_target() -> None:
    downgraded = migration._to_legacy_shape(
        json.dumps({"pooled": {"targets": ["first", "second"]}, "one": {"targets": ["x"]}})
    )

    assert downgraded is not None
    assert json.loads(downgraded) == {"one": "x", "pooled": "first"}


def test_migration_downgrade_leaves_legacy_rows_untouched() -> None:
    assert migration._to_legacy_shape(json.dumps({"a": "x"})) is None
