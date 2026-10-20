"""Stored CLIProxyAPI OAuth prefixes are read from the auth file, not rewritten.

CLIProxyAPI 8.0.30 through 8.0.36 leave ``prefix`` out of the auth-files
listing. codex-lb used to read that as "no prefix" and PATCH the same prefix
back about once a minute, and each such PATCH can race a token refresh on
CLIProxyAPI below 8.0.34 (router-for-me/CLIProxyAPI#6733).

Every auth file here is a synthetic fixture under ``tmp_path``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import pytest

from app.core.clients.claude_sidecar import ClaudeSidecarClient
from app.core.types import JsonValue
from app.modules.claude_sidecar.auth_file import read_auth_file, stored_prefix_for_entry
from app.modules.claude_sidecar.quota import (
    SidecarQuotaSnapshot,
    parse_auth_files,
    snapshot_from_json,
    snapshot_to_json,
)
from app.modules.cliproxy_accounts.management import ManagementResponse
from app.modules.proxy import cliproxy_account_routing as routing
from app.modules.proxy.cliproxy_account_routing import CliproxyCandidate, candidates_from_snapshot

pytestmark = pytest.mark.unit

_MODEL = "claude-opus-5-5"
_STORED = "lb0881c9d437"


@pytest.fixture(autouse=True)
def _clear_prefix_memory() -> None:
    routing._PREFIX_OVERLAY.clear()


@pytest.fixture
def auth_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "cli-proxy-api"
    directory.mkdir()
    monkeypatch.setattr("app.modules.claude_sidecar.auth_file.default_auth_dir", lambda: directory)
    return directory


def _write_auth(directory: Path, name: str, **fields: object) -> Path:
    path = directory / name
    payload = {
        "type": "claude",
        "email": "a@example.com",
        "access_token": "synthetic-access-token",
        "refresh_token": "synthetic-refresh-token",
        **fields,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class _CliproxyApi:
    """CLIProxyAPI management over a directory of auth files.

    Like CLIProxyAPI 8.0.30-8.0.36, the listing omits ``prefix``. A fields
    PATCH writes the prefix into the auth file, as CLIProxyAPI does.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.patches: list[tuple[str, dict[str, JsonValue]]] = []

    async def list_auth_files(self) -> list[Mapping[str, JsonValue]]:
        entries: list[Mapping[str, JsonValue]] = []
        for path in sorted(self.directory.glob("*.json")):
            stored = json.loads(path.read_text(encoding="utf-8"))
            entries.append(
                {
                    "name": path.name,
                    "provider": "claude",
                    "type": "claude",
                    "email": stored.get("email"),
                    "auth_index": path.stem,
                    "path": str(path),
                    "status": "active",
                }
            )
        return entries

    async def patch_auth_file_fields(self, name: str, fields: Mapping[str, JsonValue]) -> None:
        self.patches.append((name, dict(fields)))
        path = self.directory / name
        stored = json.loads(path.read_text(encoding="utf-8"))
        stored.update(fields)
        path.write_text(json.dumps(stored), encoding="utf-8")

    async def config_v8_request(self, method: str, path: str, body: object, if_match: str | None) -> ManagementResponse:
        assert method == "GET", "the prefix fill must not write CLIProxyAPI config"
        return ManagementResponse(status=200, etag='"v1"', body={})


async def _snapshot_candidates(client: _CliproxyApi) -> list[CliproxyCandidate]:
    """Build candidates the way routing does: listing -> stored snapshot -> candidates."""

    accounts = parse_auth_files(await client.list_auth_files(), auth_dir=client.directory)
    now = datetime.now(timezone.utc)
    stored = snapshot_to_json(
        SidecarQuotaSnapshot(checked_at=now, status="healthy", message=None, accounts=tuple(accounts))
    )
    return candidates_from_snapshot(snapshot_from_json(stored), now=now)


def _expire_prefix_memory() -> None:
    """Age every remembered prefix past ``_PREFIX_OVERLAY_SECONDS``."""

    expired = time.monotonic() - routing._PREFIX_OVERLAY_SECONDS - 1
    for account_id, (_stored_at, prefix) in list(routing._PREFIX_OVERLAY.items()):
        routing._PREFIX_OVERLAY[account_id] = (expired, prefix)


async def test_listing_without_prefix_reads_the_auth_file_and_sends_no_patch(auth_dir: Path, db_setup: bool) -> None:
    del db_setup
    _write_auth(auth_dir, "claude-a.json", prefix=_STORED)
    client = _CliproxyApi(auth_dir)
    bare = [replace(item, prefix=None) for item in await _snapshot_candidates(client)]

    for _cycle in range(3):
        filled = await routing._fill_empty_prefixes(bare, _MODEL, _sidecar(client))
        assert [item.prefix for item in filled] == [_STORED]
        _expire_prefix_memory()

    assert client.patches == []


async def test_snapshot_candidate_carries_the_on_disk_prefix(auth_dir: Path) -> None:
    _write_auth(auth_dir, "claude-a.json", prefix=_STORED)
    client = _CliproxyApi(auth_dir)

    candidates = await _snapshot_candidates(client)

    assert [item.prefix for item in candidates] == [_STORED]
    filled = await routing._fill_empty_prefixes(candidates, _MODEL, _sidecar(client))
    assert [item.prefix for item in filled] == [_STORED]
    assert client.patches == []


async def test_empty_prefix_is_written_once_then_never_again(auth_dir: Path, db_setup: bool) -> None:
    del db_setup
    _write_auth(auth_dir, "claude-a.json")
    client = _CliproxyApi(auth_dir)

    first = await routing._fill_empty_prefixes(await _snapshot_candidates(client), _MODEL, _sidecar(client))

    assert len(client.patches) == 1
    name, fields = client.patches[0]
    assert name == "claude-a.json"
    written = fields["prefix"]
    assert isinstance(written, str) and written.startswith("lb")
    assert [item.prefix for item in first] == [written]

    for _cycle in range(3):
        _expire_prefix_memory()
        later = await routing._fill_empty_prefixes(await _snapshot_candidates(client), _MODEL, _sidecar(client))
        assert [item.prefix for item in later] == [written]

    assert len(client.patches) == 1


async def test_two_credentials_keep_their_stored_prefixes_after_memory_expires(auth_dir: Path, db_setup: bool) -> None:
    del db_setup
    _write_auth(auth_dir, "claude-a.json", prefix=_STORED)
    _write_auth(auth_dir, "claude-b.json", email="b@example.com", prefix="lb2a7d4938e6")
    client = _CliproxyApi(auth_dir)
    bare = [replace(item, prefix=None) for item in await _snapshot_candidates(client)]

    await routing._fill_empty_prefixes(bare, _MODEL, _sidecar(client))
    _expire_prefix_memory()
    filled = await routing._fill_empty_prefixes(bare, _MODEL, _sidecar(client))

    assert sorted(item.prefix or "" for item in filled) == ["lb0881c9d437", "lb2a7d4938e6"]
    assert client.patches == []


def test_snapshot_parse_reads_the_prefix_from_the_auth_file(auth_dir: Path) -> None:
    path = _write_auth(auth_dir, "claude-a.json", prefix=_STORED)

    accounts = parse_auth_files([{"name": path.name, "provider": "claude", "path": str(path)}], auth_dir=auth_dir)

    assert accounts[0].prefix == _STORED


def test_listing_prefix_wins_over_the_auth_file(auth_dir: Path) -> None:
    path = _write_auth(auth_dir, "claude-a.json", prefix="on-disk")

    entry = {"name": path.name, "provider": "claude", "path": str(path), "prefix": "listed"}

    assert stored_prefix_for_entry(entry) == "listed"
    assert parse_auth_files([entry], auth_dir=auth_dir)[0].prefix == "listed"


def test_auth_file_without_a_prefix_reads_as_none(auth_dir: Path) -> None:
    path = _write_auth(auth_dir, "claude-a.json")

    assert stored_prefix_for_entry({"name": path.name, "path": str(path)}) is None
    assert stored_prefix_for_entry({"name": path.name, "path": str(path), "prefix": "  "}) is None


def test_prefix_is_never_read_from_outside_the_auth_dir(auth_dir: Path, tmp_path: Path) -> None:
    outside = _write_auth(tmp_path, "outside.json", prefix="stolen")
    traversal = auth_dir / ".." / "outside.json"
    link = auth_dir / "link.json"
    link.symlink_to(outside)

    for path in (outside, traversal, link):
        entry = {"name": "claude-a.json", "provider": "claude", "path": str(path)}
        assert stored_prefix_for_entry(entry) is None
        assert parse_auth_files([entry], auth_dir=auth_dir)[0].prefix is None
        assert routing._oauth_prefixes([entry]) == {}


def test_unreadable_auth_file_reads_as_no_prefix(auth_dir: Path) -> None:
    broken = auth_dir / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    listed = auth_dir / "list.json"
    listed.write_text("[1, 2]", encoding="utf-8")

    for entry in (
        {"name": "missing.json", "path": str(auth_dir / "missing.json")},
        {"name": "broken.json", "path": str(broken)},
        {"name": "list.json", "path": str(listed)},
        {"name": "no-path.json"},
    ):
        assert stored_prefix_for_entry(entry) is None


def test_read_auth_file_refuses_a_path_outside_the_auth_dir(tmp_path: Path) -> None:
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir()
    inside = _write_auth(auth_dir, "claude-a.json", prefix="kept")
    outside = _write_auth(tmp_path, "outside.json", prefix="stolen")

    assert read_auth_file(str(inside), auth_dir) is not None
    assert read_auth_file(str(outside), auth_dir) is None
    assert read_auth_file(None, auth_dir) is None


def _sidecar(client: _CliproxyApi) -> ClaudeSidecarClient:
    return cast(ClaudeSidecarClient, client)
