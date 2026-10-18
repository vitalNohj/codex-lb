"""API-key config writes against a real CLIProxyAPI v8 binary.

Set ``CLIPROXYAPI_BIN`` to a CLIProxyAPI v8 executable to run these tests;
they are skipped otherwise. Each test starts the binary on a free local port
with a config holding named groups, a multi-key group, and per-key fields,
drives codex-lb's API-key writes against it, and diffs the whole config file
CLIProxyAPI saved.
"""

from __future__ import annotations

import asyncio
import copy
import os
import socket
import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import aiohttp
import pytest
import pytest_asyncio
import yaml

from app.core.clients.claude_sidecar import ClaudeSidecarClient, ClaudeSidecarConfig
from app.core.clients.http import close_http_client, init_http_client
from app.modules.cliproxy_accounts.api_keys import (
    ApiKeyWrite,
    delete_api_key_account,
    list_routing_api_keys,
    set_api_key_prefix_if_empty,
    update_api_key_account,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("CLIPROXYAPI_BIN"), reason="CLIPROXYAPI_BIN is not set"),
]

_SECRET = "real-binary-mgmt-secret"
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
  auth-dir: "./auths"
api-keys:
  codex:
    - name: codex-main
      base-url: "http://127.0.0.1:1/codex"
      keys:
        - api-key: "sk-codex-1"
  claude:
    # team key comment
    - name: my-team-key
      base-url: "http://127.0.0.1:1/claude"
      priority: 3
      headers:
        X-Team: "alpha"
      excluded-models:
        - "claude-3-*"
      keys:
        - api-key: "sk-ant-team"
          weight: 5
          cloak:
            mode: always
    - name: shared-pool
      base-url: "http://127.0.0.1:1/claude"
      keys:
        - api-key: "sk-ant-pool-b"
        - api-key: "sk-ant-pool-c"
          weight: 2
  openai-compatibility:
    - name: nv
      base-url: "http://127.0.0.1:1/v1"
      keys:
        - api-key: "nv-key-1"
        - api-key: "nv-key-2"
      models:
        - name: "meta/llama"
          alias: "llama"
"""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def cliproxy(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    binary = os.environ["CLIPROXYAPI_BIN"]
    port = _free_port()
    config = tmp_path / "config.yaml"
    config.write_text(_CONFIG.format(port=port, secret=_SECRET))
    (tmp_path / "auths").mkdir()
    log = (tmp_path / "cliproxy.log").open("wb")
    process = subprocess.Popen([binary, "-config", str(config)], cwd=tmp_path, stdout=log, stderr=log)
    try:
        yield f"http://127.0.0.1:{port}", config
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        log.close()


@pytest_asyncio.fixture
async def sidecar(cliproxy: tuple[str, Path]) -> AsyncIterator[tuple[ClaudeSidecarClient, Path]]:
    base_url, config = cliproxy
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
        yield client, config
    finally:
        await close_http_client()


async def _wait_ready(base_url: str) -> None:
    headers = {"Authorization": f"Bearer {_SECRET}"}
    async with aiohttp.ClientSession() as session:
        for _ in range(100):
            try:
                async with session.get(f"{base_url}/v8/management/config/api-keys", headers=headers) as resp:
                    if resp.status == 200:
                        return
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(0.1)
    raise AssertionError("CLIProxyAPI did not start")


def _saved(config: Path) -> dict[str, object]:
    loaded = yaml.safe_load(config.read_text())
    assert isinstance(loaded, dict)
    return loaded


def _api_keys(tree: dict[str, object]) -> dict[str, list[dict[str, object]]]:
    api_keys = tree["api-keys"]
    assert isinstance(api_keys, dict)
    return api_keys


@pytest.mark.asyncio
async def test_prefix_writes_change_only_the_prefix_in_the_saved_config(sidecar) -> None:
    client, config = sidecar
    before = _saved(config)
    rows = {row.name: row for row in await list_routing_api_keys(client)}
    assert sorted(rows) == ["codex-main#1", "my-team-key#1", "nv", "shared-pool#1", "shared-pool#2"]

    for name, prefix in (("my-team-key#1", "lbteam"), ("shared-pool#2", "lbpoolc"), ("nv", "lbnv")):
        row = rows[name]
        stored = await set_api_key_prefix_if_empty(
            client, kind_slug=row.kind, route_identity=row.route_identity, prefix=prefix
        )
        assert stored == prefix

    after = _saved(config)
    expected = copy.deepcopy(before)
    keys = _api_keys(expected)
    keys["claude"][0]["prefix"] = "lbteam"
    pool_keys = keys["claude"][1]["keys"]
    assert isinstance(pool_keys, list)
    pool_keys[1]["prefix"] = "lbpoolc"
    keys["openai-compatibility"][0]["prefix"] = "lbnv"
    assert after == expected

    # CLIProxyAPI routes each prefix to exactly the credential it was written for,
    # and the auth indexes (sticky pin identities) did not move.
    routed = {row.name: row for row in await list_routing_api_keys(client)}
    assert {name: row.prefix for name, row in routed.items()} == {
        "codex-main#1": None,
        "my-team-key#1": "lbteam",
        "nv": "lbnv",
        "shared-pool#1": None,
        "shared-pool#2": "lbpoolc",
    }
    assert {name: row.route_identity for name, row in routed.items()} == {
        name: row.route_identity for name, row in rows.items()
    }
    for row in routed.values():
        assert row.auth_index == row.route_identity


@pytest.mark.asyncio
async def test_form_edit_and_delete_keep_every_other_group(sidecar) -> None:
    client, config = sidecar
    before = _saved(config)
    from app.modules.cliproxy_accounts.api_keys import API_KEY_KINDS, _entries, _read_config, api_key_account_id

    snapshot = await _read_config(client)
    claude = API_KEY_KINDS["claude"]
    entries = _entries(claude, snapshot.families["claude"])
    pool_b = entries[1]
    write = ApiKeyWrite(
        kind="claude",
        name=None,
        base_url="http://127.0.0.1:1/claude",
        api_key=None,
        models=(),
        disabled=None,
        update_models=False,
        update_disabled=False,
        update_name=False,
        prefix="poolb",
        update_prefix=True,
    )
    account = await update_api_key_account(client, [], pool_b.index, write, api_key_account_id(claude, pool_b.item))
    assert account.prefix == "poolb"
    assert account.group == "shared-pool"

    team = entries[0]
    await delete_api_key_account(client, "claude", team.index, api_key_account_id(claude, team.item))

    after = _saved(config)
    expected = copy.deepcopy(before)
    keys = _api_keys(expected)
    pool_keys = keys["claude"][1]["keys"]
    assert isinstance(pool_keys, list)
    pool_keys[0]["prefix"] = "poolb"
    del keys["claude"][0]
    assert after == expected
