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


def test_dump_writes_single_targets_as_strings_and_pools_as_objects_sorted_and_compact() -> None:
    dumped = dump_alias_pools_json(
        {"c": ModelAliasPool(targets=("p", "q")), "b": ModelAliasPool(targets=("y",)), "a": {"targets": ["x"]}}
    )

    assert dumped == '{"a":"x","b":"y","c":{"targets":["p","q"]}}'
    assert parse_alias_pools_json(dumped) == normalize_alias_pools({"a": "x", "b": "y", "c": {"targets": ["p", "q"]}})


def _previous_release_parse(raw: str) -> dict[str, str]:
    """The previous release's ``_parse_model_aliases``, verbatim in behavior."""

    aliases: dict[str, str] = {}
    seen: set[str] = set()
    for alias, target in json.loads(raw).items():
        if not isinstance(alias, str) or not isinstance(target, str):
            continue
        normalized_alias, normalized_target = alias.strip(), target.strip()
        if not normalized_alias or not normalized_target or normalized_alias.lower() in seen:
            continue
        seen.add(normalized_alias.lower())
        aliases[normalized_alias] = normalized_target
    return aliases


def test_a_previous_release_replica_reads_every_single_target_alias_this_release_stores() -> None:
    # During a rolling upgrade an old replica reads the row and, on any
    # settings save, writes back only what it read. A single alias it could
    # not read would be erased by that save.
    stored = dump_alias_pools_json({"custom_r1": "cc/claude", "fast": ModelAliasPool(targets=("gpt-5.4",))})

    assert _previous_release_parse(stored) == {"custom_r1": "cc/claude", "fast": "gpt-5.4"}


def test_plain_shape_round_trips() -> None:
    pools = {"pooled/glm": ModelAliasPool(targets=("or/glm", "orca/glm"))}

    assert alias_pools_to_plain(pools) == {"pooled/glm": {"targets": ["or/glm", "orca/glm"]}}


def test_find_alias_pool_case_insensitive() -> None:
    pools = {"Pooled/GLM": ModelAliasPool(targets=("or/glm",))}

    assert find_alias_pool("pooled/glm", pools) == ("Pooled/GLM", pools["Pooled/GLM"])
    assert find_alias_pool("other", pools) is None
    assert find_alias_pool(None, pools) is None
    assert find_alias_pool("  ", pools) is None


def test_migration_upgrade_leaves_legacy_and_pool_rows_untouched() -> None:
    # Legacy strings are the stored form of a single-target alias, so an old
    # replica still reads them after the upgrade.
    assert migration._to_legacy_shape(json.dumps({"custom_r1": "cc/claude", "b": " x "})) is None
    assert migration._to_legacy_shape(json.dumps({"a": {"targets": ["x", "y"]}})) is None
    assert migration._to_legacy_shape("{}") is None
    assert migration._to_legacy_shape(None) is None
    assert migration._to_legacy_shape("not json") is None


def test_migration_rewrites_a_one_target_object_to_its_string_in_both_directions() -> None:
    rewritten = migration._to_legacy_shape(json.dumps({"one": {"targets": ["x"]}, "legacy": "y"}))

    assert rewritten is not None
    assert json.loads(rewritten) == {"legacy": "y", "one": "x"}


def test_migration_downgrade_turns_one_target_pools_back_into_strings() -> None:
    downgraded = migration._to_legacy_shape(json.dumps({"one": {"targets": [" x "]}, "legacy": "y"}))

    assert downgraded is not None
    assert json.loads(downgraded) == {"legacy": "y", "one": "x"}


def test_migration_downgrade_never_truncates_a_pool() -> None:
    # ``downgrade`` refuses while such a pool exists; the rewrite itself must
    # not discard fallback targets either.
    downgraded = migration._to_legacy_shape(
        json.dumps({"pooled": {"targets": ["first", "second"]}, "one": {"targets": ["x"]}})
    )

    assert downgraded is not None
    assert json.loads(downgraded) == {"one": "x", "pooled": {"targets": ["first", "second"]}}


def test_migration_downgrade_names_the_aliases_blocking_it() -> None:
    raw = json.dumps({"pooled": {"targets": ["a", "b"]}, "one": {"targets": ["x"]}, "legacy": "y"})

    assert migration._fallback_aliases(raw) == ["pooled"]
    assert migration._fallback_aliases(json.dumps({"dupes": {"targets": ["a", "A"]}})) == []
    assert "alias 'pooled' has fallback targets" in migration._downgrade_refusal(["pooled"])
    assert "'a9' and 2 more have" in migration._downgrade_refusal([f"a{i}" for i in range(12)])


def test_migration_downgrade_leaves_legacy_rows_untouched() -> None:
    assert migration._to_legacy_shape(json.dumps({"a": "x"})) is None
