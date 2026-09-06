"""Unit tests for CLIProxyAPI per-account model exclusion helpers.

Every auth file here is a synthetic fixture written into ``tmp_path``; no real
CLIProxyAPI credential is read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.claude_sidecar.excluded_models import (
    MAX_PATTERN_LENGTH,
    MAX_PATTERNS,
    excluded_models_for_entry,
    excluded_models_from_auth_file,
    excluded_models_from_mapping,
    normalize_excluded_models,
)


def _write_auth_file(directory: Path, name: str, payload: dict[str, object]) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestNormalizeExcludedModels:
    def test_trims_and_preserves_order(self) -> None:
        assert normalize_excluded_models(["  a-* ", "b-*"]) == ["a-*", "b-*"]

    def test_dedupes_case_insensitively_keeping_first_spelling(self) -> None:
        assert normalize_excluded_models(["Alpha-*", "alpha-*", "beta"]) == ["Alpha-*", "beta"]

    def test_empty_input_returns_empty_list(self) -> None:
        assert normalize_excluded_models([]) == []
        assert normalize_excluded_models(None) == []
        assert normalize_excluded_models("alpha-*") == []
        assert normalize_excluded_models({"alpha-*": True}) == []

    def test_drops_blank_and_non_string_entries(self) -> None:
        assert normalize_excluded_models(["", "   ", 5, True, None, "keep"]) == ["keep"]

    @pytest.mark.parametrize("bad", ["a\nb", "a\rb", "a\x00b"])
    def test_rejects_control_characters(self, bad: str) -> None:
        assert normalize_excluded_models([bad, "ok"]) == ["ok"]

    def test_rejects_commas(self) -> None:
        # CLIProxyAPI comma-joins this list internally and splits on "," when
        # routing, so an embedded comma would corrupt one pattern into two.
        assert normalize_excluded_models(["alpha-*,beta-*", "ok-*"]) == ["ok-*"]

    def test_drops_overlong_entries(self) -> None:
        long_pattern = "x" * (MAX_PATTERN_LENGTH + 1)
        at_limit = "y" * MAX_PATTERN_LENGTH
        assert normalize_excluded_models([long_pattern, at_limit]) == [at_limit]

    def test_caps_entry_count(self) -> None:
        result = normalize_excluded_models([f"model-{index}" for index in range(MAX_PATTERNS + 10)])
        assert len(result) == MAX_PATTERNS
        assert result[0] == "model-0"


class TestExcludedModelsFromMapping:
    def test_reads_snake_case_key(self) -> None:
        assert excluded_models_from_mapping({"excluded_models": ["a-*"]}) == ["a-*"]

    def test_falls_back_to_kebab_case_key(self) -> None:
        assert excluded_models_from_mapping({"excluded-models": ["a-*"]}) == ["a-*"]

    def test_snake_case_wins_when_both_present(self) -> None:
        entry = {"excluded_models": ["snake-*"], "excluded-models": ["kebab-*"]}
        assert excluded_models_from_mapping(entry) == ["snake-*"]

    def test_missing_key_returns_empty_list(self) -> None:
        assert excluded_models_from_mapping({"name": "claude-a.json"}) == []

    def test_null_value_reads_as_an_available_empty_list(self) -> None:
        # Go marshals a nil slice as null unless tagged omitempty, so a list that
        # was set and later cleared persists this way. That is a successful read
        # of "no exclusions", not a failure that should lock the editor.
        assert excluded_models_from_mapping({"excluded_models": None}) == []
        assert excluded_models_from_mapping({"excluded-models": None}) == []

    def test_comma_joined_string_form_is_unreadable(self) -> None:
        # A present key whose value is not a list of strings is not a successful
        # read: reporting [] would offer an unlocked empty editor over a real list.
        assert excluded_models_from_mapping({"excluded_models": "a-*,b-*"}) is None
        assert excluded_models_from_mapping({"excluded-models": "a-*,b-*"}) is None

    def test_non_string_entries_make_the_list_unreadable(self) -> None:
        assert excluded_models_from_mapping({"excluded_models": ["a-*", 7]}) is None

    def test_list_that_normalization_would_change_is_unreadable(self) -> None:
        # Read-side normalization is display-only: a save replaces the whole
        # list, so handing back a shortened copy would delete the rest on disk.
        assert excluded_models_from_mapping({"excluded_models": ["  a-* "]}) is None
        assert excluded_models_from_mapping({"excluded_models": ["a-*", "A-*"]}) is None
        assert excluded_models_from_mapping({"excluded_models": ["a-*,b-*"]}) is None
        assert excluded_models_from_mapping({"excluded_models": ["x" * (MAX_PATTERN_LENGTH + 1)]}) is None
        over_cap = [f"model-{index}" for index in range(MAX_PATTERNS + 1)]
        assert excluded_models_from_mapping({"excluded_models": over_cap}) is None


class TestExcludedModelsFromAuthFile:
    def test_returns_only_the_exclusion_list(self, tmp_path: Path) -> None:
        path = _write_auth_file(
            tmp_path,
            "claude-a.json",
            {
                "access_token": "synthetic-access-token",
                "refresh_token": "synthetic-refresh-token",
                "email": "a@example.com",
                "excluded_models": ["alpha-*", "beta-5*"],
            },
        )
        result = excluded_models_from_auth_file(str(path), auth_dir=tmp_path)
        assert result == ["alpha-*", "beta-5*"]
        assert not any("token" in entry for entry in result)

    def test_kebab_case_key_in_file(self, tmp_path: Path) -> None:
        path = _write_auth_file(tmp_path, "claude-b.json", {"excluded-models": ["alpha-*"]})
        assert excluded_models_from_auth_file(str(path), auth_dir=tmp_path) == ["alpha-*"]

    def test_readable_file_without_the_key_returns_an_empty_list(self, tmp_path: Path) -> None:
        path = _write_auth_file(tmp_path, "claude-none.json", {"email": "a@example.com"})
        assert excluded_models_from_auth_file(str(path), auth_dir=tmp_path) == []

    def test_null_exclusion_value_in_file_reads_as_empty(self, tmp_path: Path) -> None:
        path = _write_auth_file(tmp_path, "claude-null.json", {"excluded_models": None})
        assert excluded_models_from_auth_file(str(path), auth_dir=tmp_path) == []

    def test_missing_file_is_unreadable(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.json"
        assert excluded_models_from_auth_file(str(missing), auth_dir=tmp_path) is None

    def test_empty_path_is_unreadable(self, tmp_path: Path) -> None:
        assert excluded_models_from_auth_file(None, auth_dir=tmp_path) is None
        assert excluded_models_from_auth_file("", auth_dir=tmp_path) is None
        assert excluded_models_from_auth_file("   ", auth_dir=tmp_path) is None

    def test_path_escaping_the_auth_dir_is_unreadable(self, tmp_path: Path) -> None:
        auth_dir = tmp_path / "auth"
        auth_dir.mkdir()
        outside = _write_auth_file(tmp_path, "outside.json", {"excluded_models": ["alpha-*"]})
        assert excluded_models_from_auth_file(str(outside), auth_dir=auth_dir) is None
        traversal = auth_dir / ".." / "outside.json"
        assert excluded_models_from_auth_file(str(traversal), auth_dir=auth_dir) is None

    def test_malformed_json_is_unreadable(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        assert excluded_models_from_auth_file(str(path), auth_dir=tmp_path) is None

    def test_non_object_json_is_unreadable(self, tmp_path: Path) -> None:
        path = tmp_path / "list.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        assert excluded_models_from_auth_file(str(path), auth_dir=tmp_path) is None

    def test_file_needing_normalization_is_unreadable(self, tmp_path: Path) -> None:
        path = _write_auth_file(
            tmp_path,
            "claude-c.json",
            {"excluded_models": ["  alpha-* ", "ALPHA-*", "", 7]},
        )
        assert excluded_models_from_auth_file(str(path), auth_dir=tmp_path) is None

    def test_over_cap_file_is_unreadable_rather_than_truncated(self, tmp_path: Path) -> None:
        patterns = [f"claude-{index}-*" for index in range(MAX_PATTERNS + 8)]
        path = _write_auth_file(tmp_path, "claude-many.json", {"excluded_models": patterns})
        assert excluded_models_from_auth_file(str(path), auth_dir=tmp_path) is None


class TestExcludedModelsForEntry:
    def test_prefers_the_listing_entry_field(self, tmp_path: Path) -> None:
        path = _write_auth_file(tmp_path, "claude-d.json", {"excluded_models": ["from-file-*"]})
        entry = {"path": str(path), "excluded_models": ["from-entry-*"]}
        assert excluded_models_for_entry(entry, auth_dir=tmp_path) == ["from-entry-*"]

    def test_entry_field_present_but_empty_skips_the_file(self, tmp_path: Path) -> None:
        path = _write_auth_file(tmp_path, "claude-e.json", {"excluded_models": ["from-file-*"]})
        entry = {"path": str(path), "excluded_models": []}
        assert excluded_models_for_entry(entry, auth_dir=tmp_path) == []

    def test_falls_back_to_the_file_when_the_entry_omits_the_field(self, tmp_path: Path) -> None:
        path = _write_auth_file(
            tmp_path,
            "claude-f.json",
            {"access_token": "synthetic-access-token", "excluded_models": ["from-file-*"]},
        )
        assert excluded_models_for_entry({"path": str(path)}, auth_dir=tmp_path) == ["from-file-*"]

    def test_no_field_and_no_path_is_unreadable(self, tmp_path: Path) -> None:
        assert excluded_models_for_entry({"name": "claude-g.json"}, auth_dir=tmp_path) is None

    def test_unreadable_file_is_unreadable(self, tmp_path: Path) -> None:
        entry = {"path": str(tmp_path / "missing.json")}
        assert excluded_models_for_entry(entry, auth_dir=tmp_path) is None

    def test_entry_field_in_string_form_is_unreadable(self, tmp_path: Path) -> None:
        path = _write_auth_file(tmp_path, "claude-h.json", {"excluded_models": ["from-file-*"]})
        entry = {"path": str(path), "excluded_models": "claude-fable-*,claude-opus-5*"}
        assert excluded_models_for_entry(entry, auth_dir=tmp_path) is None
