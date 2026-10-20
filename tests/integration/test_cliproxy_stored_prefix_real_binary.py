"""Stored OAuth prefixes against a real CLIProxyAPI binary.

Set ``CLIPROXYAPI_BIN`` to a CLIProxyAPI v8 executable to run this test; it is
skipped otherwise. The binary starts on a free local port with two fake Claude
OAuth credentials, one with a stored prefix and one without, and no upstream
is ever called. The test checks that CLIProxyAPI's auth-files listing omits
``prefix``, then runs codex-lb's prefix fill for several cycles and reads back
CLIProxyAPI's own log: exactly one fields PATCH, for the credential that had
no prefix.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import time
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import pytest
import pytest_asyncio

from app.core.clients.claude_sidecar import ClaudeSidecarClient, ClaudeSidecarConfig
from app.core.clients.http import close_http_client, init_http_client
from app.modules.claude_sidecar.quota import (
    SidecarQuotaSnapshot,
    parse_auth_files,
    snapshot_from_json,
    snapshot_to_json,
)
from app.modules.proxy import cliproxy_account_routing as routing
from app.modules.proxy.cliproxy_account_routing import candidates_from_snapshot

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("CLIPROXYAPI_BIN"), reason="CLIPROXYAPI_BIN is not set"),
]

_SECRET = "real-binary-mgmt-secret"
_MODEL = "claude-opus-4-5"
_STORED = "lbstored0001"
_CONFIG = """\
config-version: 8
server:
  host: "127.0.0.1"
  port: {port}
management:
  allow-remote: false
  secret-key: "{secret}"
access:
  api-keys:
    - "client-key"
oauth:
  auth-dir: "{auth_dir}"
request-retry: 0
"""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _fake_claude(email: str, **fields: object) -> str:
    return json.dumps(
        {
            "type": "claude",
            "email": email,
            "access_token": f"FAKE-access-{email}",
            "refresh_token": f"FAKE-refresh-{email}",
            "expired": "2099-01-01T00:00:00Z",
            "last_refresh": "2026-10-20T00:00:00Z",
            **fields,
        }
    )


@pytest.fixture
def cliproxy(tmp_path: Path) -> Iterator[tuple[str, Path, Path]]:
    binary = os.environ["CLIPROXYAPI_BIN"]
    port = _free_port()
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    (auth_dir / "claude-stored.json").write_text(_fake_claude("stored@example.com", prefix=_STORED))
    (auth_dir / "claude-empty.json").write_text(_fake_claude("empty@example.com"))
    config = tmp_path / "config.yaml"
    config.write_text(_CONFIG.format(port=port, secret=_SECRET, auth_dir=auth_dir))
    home = tmp_path / "home"
    home.mkdir()
    log_path = tmp_path / "cliproxy.log"
    log = log_path.open("wb")
    process = subprocess.Popen(
        [binary, "-config", str(config)],
        cwd=tmp_path,
        stdout=log,
        stderr=log,
        env={**os.environ, "HOME": str(home)},
    )
    try:
        yield f"http://127.0.0.1:{port}", auth_dir, log_path
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        log.close()


@pytest_asyncio.fixture
async def sidecar(
    cliproxy: tuple[str, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[ClaudeSidecarClient, Path, Path]]:
    base_url, auth_dir, log_path = cliproxy
    monkeypatch.setattr("app.modules.claude_sidecar.auth_file.default_auth_dir", lambda: auth_dir)
    await init_http_client()
    try:
        await _wait_ready(base_url)
        client = ClaudeSidecarClient(
            ClaudeSidecarConfig(
                enabled=True,
                base_url=base_url,
                api_key="client-key",
                prefixes=(),
                connect_timeout_seconds=5,
                request_timeout_seconds=10,
                models_cache_ttl_seconds=60,
                management_key=_SECRET,
            )
        )
        yield client, auth_dir, log_path
    finally:
        await close_http_client()


async def _wait_ready(base_url: str) -> None:
    headers = {"Authorization": f"Bearer {_SECRET}"}
    async with aiohttp.ClientSession() as session:
        for _ in range(150):
            try:
                async with session.get(f"{base_url}/v0/management/auth-files", headers=headers) as resp:
                    if resp.status == 200 and len((await resp.json()).get("files", [])) == 2:
                        return
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(0.1)
    raise AssertionError("CLIProxyAPI did not start with both fake Claude credentials")


async def _candidates(client: ClaudeSidecarClient, auth_dir: Path) -> list[routing.CliproxyCandidate]:
    """Listing -> stored quota snapshot -> candidates, as the poller and router do."""

    accounts = parse_auth_files(await client.list_auth_files(), auth_dir=auth_dir)
    now = datetime.now(timezone.utc)
    stored = snapshot_to_json(
        SidecarQuotaSnapshot(checked_at=now, status="healthy", message=None, accounts=tuple(accounts))
    )
    return candidates_from_snapshot(snapshot_from_json(stored), now=now)


def _fields_patches(log_path: Path) -> int:
    return log_path.read_text(errors="replace").count("/v0/management/auth-files/fields")


@pytest.mark.asyncio
async def test_stored_prefix_is_not_rewritten_by_the_prefix_fill(sidecar, db_setup: bool) -> None:
    del db_setup
    client, auth_dir, log_path = sidecar
    routing._PREFIX_OVERLAY.clear()

    listed = await client.list_auth_files()
    assert {entry.get("name") for entry in listed} == {"claude-stored.json", "claude-empty.json"}
    # The bug's root cause: CLIProxyAPI does not list the stored prefix.
    assert all("prefix" not in entry for entry in listed)

    by_name = {item.name: item.prefix for item in await _candidates(client, auth_dir)}
    assert by_name == {"claude-stored.json": _STORED, "claude-empty.json": None}

    written: set[str] = set()
    for _cycle in range(3):
        filled = await routing._fill_empty_prefixes(await _candidates(client, auth_dir), _MODEL, client)
        prefixes = {item.name: item.prefix for item in filled}
        assert prefixes["claude-stored.json"] == _STORED
        assert prefixes["claude-empty.json"] is not None
        written.add(prefixes["claude-empty.json"])
        # Age the in-process memory past its 60 s window, as on a live host.
        expired = time.monotonic() - routing._PREFIX_OVERLAY_SECONDS - 1
        for account_id, (_at, prefix) in list(routing._PREFIX_OVERLAY.items()):
            routing._PREFIX_OVERLAY[account_id] = (expired, prefix)

    assert len(written) == 1
    on_disk = json.loads((auth_dir / "claude-empty.json").read_text())
    assert on_disk["prefix"] == written.pop()
    assert json.loads((auth_dir / "claude-stored.json").read_text())["prefix"] == _STORED
    assert _fields_patches(log_path) == 1
