"""Contract tests for per-account exclusions against a real CLIProxyAPI binary.

Every other exclusion test in this suite substitutes a fake sidecar client, so it
proves what codex-lb *sends* and nothing about what CLIProxyAPI *does* with it.
These tests instead start an actual CLIProxyAPI executable over synthetic auth
files, save exclusions through codex-lb's own management endpoint, and then read
which accounts CLIProxyAPI's selector reports as eligible for a model.

CLIProxyAPI applies an account's ``excluded_models`` when it registers that
credential's model catalog, and the selector then only considers accounts whose
registered catalog still carries the requested wire id
(``authSupportsRouteModel`` -> ``ClientSupportsModel``). So
``GET /v0/management/auth-files/models?name=<auth file>`` is the selector's own
eligibility answer for one account: an excluded wire id is absent from the
account that excludes it and present on every account that does not. That is
asserted here against the real binary rather than restating the desired rule.

The suite skips unless ``CODEX_LB_CLIPROXY_BINARY`` points at a CLIProxyAPI
executable, and it never contacts a provider. Isolation is enforced by the
kernel, not by convention: the process runs under ``sandbox-exec`` with a policy
that denies every non-loopback socket, so a Claude attempt with a synthetic token
cannot reach ``api.anthropic.com`` even though CLIProxyAPI's Claude executor
targets that host directly. Credentials are synthetic, and the auth directory is
a per-test temporary directory, never the operator's real one.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.integration

_CLIENT_KEY = "synthetic-client-key"
_MANAGEMENT_KEY = "synthetic-management-key"
# Wire ids from CLIProxyAPI's own bundled Claude catalog. The exact/wildcard
# distinction needs two ids that share a prefix but are not each other.
_MODEL_EXACT = "claude-opus-4-6"
_MODEL_SIBLING = "claude-opus-4-7"
_MODEL_OUTSIDE = "claude-opus-5"
_WILDCARD = "claude-opus-4-*"
_ALIAS = "synthetic-house-model"

_ALPHA = "claude-alpha.json"
_BRAVO = "claude-bravo.json"


def _binary() -> str:
    configured = os.environ.get("CODEX_LB_CLIPROXY_BINARY", "").strip()
    if not configured:
        pytest.skip("set CODEX_LB_CLIPROXY_BINARY to a CLIProxyAPI executable to run the contract tests")
    resolved = shutil.which(configured) or configured
    if not Path(resolved).is_file():
        pytest.skip(f"CODEX_LB_CLIPROXY_BINARY does not point at a file: {configured}")
    return resolved


def _sandbox_exec() -> str:
    """Return the sandbox wrapper that confines the sidecar to loopback sockets.

    CLIProxyAPI's Claude executor sends to ``api.anthropic.com`` regardless of an
    auth file's ``base_url``, so a model attempt with a synthetic token would
    otherwise leave the machine. These tests require a kernel-enforced network
    boundary and skip rather than run without one.
    """
    if sys.platform != "darwin":
        pytest.skip("the loopback-only network boundary requires macOS sandbox-exec")
    resolved = shutil.which("sandbox-exec")
    if resolved is None:
        pytest.skip("sandbox-exec is required to confine the sidecar to loopback")
    return resolved


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_auth_file(
    auth_dir: Path,
    name: str,
    email: str,
    token: str,
    upstream: str,
    *,
    model_aliases: list[dict[str, str]] | None = None,
) -> None:
    payload: dict[str, object] = {
        "type": "claude",
        "email": email,
        "access_token": token,
        "refresh_token": f"synthetic-refresh-{token}",
        "expired": "2099-01-01T00:00:00Z",
        "base_url": upstream,
    }
    if model_aliases is not None:
        payload["model_aliases"] = model_aliases
    (auth_dir / name).write_text(json.dumps(payload), encoding="utf-8")


class _Sidecar:
    """A running CLIProxyAPI process over synthetic auth files."""

    def __init__(self, base_url: str, auth_dir: Path, log_path: Path | None = None) -> None:
        self.base_url = base_url
        self.auth_dir = auth_dir
        self.log_path = log_path

    def models_for_account(self, name: str) -> set[str]:
        """Return the wire model ids CLIProxyAPI currently offers for one account."""
        response = httpx.get(
            f"{self.base_url}/v0/management/auth-files/models",
            headers={"Authorization": f"Bearer {_MANAGEMENT_KEY}"},
            params={"name": name},
            timeout=10.0,
        )
        response.raise_for_status()
        body = response.json()
        entries = body.get("models") or body.get("data") or []
        return {entry["id"] for entry in entries if isinstance(entry, dict) and "id" in entry}

    def eligible_accounts(self, model: str) -> set[str]:
        """Return the accounts whose registered catalog still offers ``model``."""
        return {name for name in (_ALPHA, _BRAVO) if model in self.models_for_account(name)}

    def stored_exclusions(self, name: str) -> object:
        return json.loads((self.auth_dir / name).read_text(encoding="utf-8")).get("excluded_models")

    def reached_a_provider(self) -> bool:
        """Report whether any attempt got an answer from a real upstream.

        Under the loopback-only policy an outbound connection is refused by the
        kernel, so an upstream HTTP status in the log would mean the boundary did
        not hold and the assertions below would be reading live provider results.
        """
        if self.log_path is None or not self.log_path.exists():
            return False
        text = self.log_path.read_text(encoding="utf-8", errors="replace")
        return "request error, error status:" in text

    def accounts_called_for(self, model: str, attempts: int = 4) -> set[str]:
        """Return every account CLIProxyAPI selected across attempts and retries.

        The synthetic upstream address has no listener, so each attempt fails and
        CLIProxyAPI exercises its in-request retry path over the remaining
        eligible accounts. The selection log therefore names every account the
        request could reach, not only the first pick.
        """
        assert self.log_path is not None
        before = len(self.log_path.read_text(encoding="utf-8", errors="replace").splitlines())
        for _ in range(attempts):
            try:
                httpx.post(
                    f"{self.base_url}/v1/messages",
                    headers={"Authorization": f"Bearer {_CLIENT_KEY}"},
                    json={
                        "model": model,
                        "max_tokens": 16,
                        "messages": [{"role": "user", "content": "hi"}],
                    },
                    timeout=30.0,
                )
            except httpx.HTTPError:
                pass
        lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[before:]
        marker = re.compile(r"auth_file=(\S+\.json) for model " + re.escape(model) + r"\s*$")
        return {match.group(1) for line in lines if (match := marker.search(line))}


def _start_sidecar(tmp_path: Path, model_aliases: list[dict[str, str]] | None) -> Iterator[_Sidecar]:
    binary = _binary()
    sandbox = _sandbox_exec()
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir()
    port = _free_port()
    # A loopback address that nothing listens on: the tests never send a model
    # request, and if one were ever added it could not leave the machine.
    upstream = f"http://127.0.0.1:{_free_port()}"
    _write_auth_file(
        auth_dir, _ALPHA, "alpha@synthetic.invalid", "synthetic-token-alpha", upstream, model_aliases=model_aliases
    )
    _write_auth_file(
        auth_dir, _BRAVO, "bravo@synthetic.invalid", "synthetic-token-bravo", upstream, model_aliases=model_aliases
    )

    config = tmp_path / "config.yaml"
    config.write_text(
        "\n".join(
            [
                'host: "127.0.0.1"',
                f"port: {port}",
                f'auth-dir: "{auth_dir}"',
                "api-keys:",
                f'  - "{_CLIENT_KEY}"',
                "remote-management:",
                "  allow-remote: false",
                f'  secret-key: "{_MANAGEMENT_KEY}"',
                "  disable-control-panel: true",
                # Selection is only observable per attempt at debug level.
                "debug: true",
                "routing:",
                '  strategy: "round-robin"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    log_path = tmp_path / "cliproxy.log"
    log_handle = log_path.open("w", encoding="utf-8")
    policy = (
        "(version 1)(allow default)(deny network*)"
        '(allow network-bind (local ip "localhost:*"))'
        '(allow network-inbound (local ip "localhost:*"))'
        '(allow network-outbound (remote ip "localhost:*"))'
        "(allow network* (remote unix-socket))(allow network* (local unix-socket))"
    )
    process = subprocess.Popen(  # noqa: S603 - operator-supplied binary, fixed args
        [sandbox, "-p", policy, binary, "--config", str(config)],
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 60.0
        while True:
            returncode = process.poll()
            if returncode is not None:
                pytest.fail(f"CLIProxyAPI executable exited during startup with code {returncode}")
            try:
                probe = httpx.get(
                    f"{base_url}/v0/management/auth-files",
                    headers={"Authorization": f"Bearer {_MANAGEMENT_KEY}"},
                    timeout=2.0,
                )
                if probe.status_code == 200 and len(probe.json().get("files") or []) == 2:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                pytest.fail("CLIProxyAPI executable did not become ready within 60 seconds")
            time.sleep(0.5)
        yield _Sidecar(base_url, auth_dir, log_path)
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=15)
        log_handle.close()


@pytest.fixture
def sidecar(tmp_path: Path) -> Iterator[_Sidecar]:
    yield from _start_sidecar(tmp_path, None)


@pytest.fixture
def aliasing_sidecar(tmp_path: Path) -> Iterator[_Sidecar]:
    """Both synthetic accounts additionally alias the excludable wire id."""
    yield from _start_sidecar(tmp_path, [{"name": _MODEL_EXACT, "alias": _ALIAS}])


async def _configure_codex_lb(async_client, base_url: str) -> None:
    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarBaseUrl": base_url,
            "claudeSidecarApiKey": _CLIENT_KEY,
            "claudeSidecarManagementKey": _MANAGEMENT_KEY,
        },
    )
    assert response.status_code == 200, response.text


async def _save_exclusions(async_client, name: str, patterns: list[str]) -> dict:
    response = await async_client.put(
        "/api/claude-sidecar/routing/excluded-models",
        json={"name": name, "excludedModels": patterns},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "healthy", body
    # CLIProxyAPI re-synthesizes the auth from disk on a file-watcher event;
    # eligibility is asserted only after that has been applied.
    time.sleep(3.0)
    return body


@pytest.mark.asyncio
async def test_exact_exclusion_skips_only_that_wire_id(async_client, sidecar):
    """An exact entry removes one account for one id, and nothing else."""
    await _configure_codex_lb(async_client, sidecar.base_url)

    assert sidecar.eligible_accounts(_MODEL_EXACT) == {_ALPHA, _BRAVO}

    await _save_exclusions(async_client, _ALPHA, [_MODEL_EXACT])

    # The excluded account is not eligible; the other account can still serve.
    assert sidecar.eligible_accounts(_MODEL_EXACT) == {_BRAVO}
    # An exact id must not implicitly cover a neighbouring version, and must not
    # touch an unrelated model or the other account's independent list.
    assert sidecar.eligible_accounts(_MODEL_SIBLING) == {_ALPHA, _BRAVO}
    assert sidecar.eligible_accounts(_MODEL_OUTSIDE) == {_ALPHA, _BRAVO}
    assert sidecar.stored_exclusions(_BRAVO) is None


@pytest.mark.asyncio
async def test_explicit_wildcard_exclusion_skips_every_matching_wire_id(async_client, sidecar):
    """An explicit wildcard covers each matching id, and stops at the pattern."""
    await _configure_codex_lb(async_client, sidecar.base_url)

    await _save_exclusions(async_client, _ALPHA, [_WILDCARD])

    assert sidecar.eligible_accounts(_MODEL_EXACT) == {_BRAVO}
    assert sidecar.eligible_accounts(_MODEL_SIBLING) == {_BRAVO}
    # Outside the configured pattern, so eligibility is unchanged.
    assert sidecar.eligible_accounts(_MODEL_OUTSIDE) == {_ALPHA, _BRAVO}


@pytest.mark.asyncio
async def test_no_eligible_account_remains_when_every_account_excludes(async_client, sidecar):
    """With no eligible account left, no excluded account becomes eligible."""
    await _configure_codex_lb(async_client, sidecar.base_url)

    await _save_exclusions(async_client, _ALPHA, [_MODEL_EXACT])
    await _save_exclusions(async_client, _BRAVO, [_MODEL_EXACT])

    assert sidecar.eligible_accounts(_MODEL_EXACT) == set()
    # Exhaustion is confined to the excluded id; permitted models are unaffected.
    assert sidecar.eligible_accounts(_MODEL_SIBLING) == {_ALPHA, _BRAVO}


@pytest.mark.asyncio
async def test_clearing_an_exclusion_restores_eligibility_without_restart(async_client, sidecar):
    """Saving and clearing both take effect in the already-running process."""
    await _configure_codex_lb(async_client, sidecar.base_url)

    await _save_exclusions(async_client, _ALPHA, [_MODEL_EXACT])
    assert sidecar.eligible_accounts(_MODEL_EXACT) == {_BRAVO}

    await _save_exclusions(async_client, _ALPHA, [])

    assert sidecar.eligible_accounts(_MODEL_EXACT) == {_ALPHA, _BRAVO}
    assert sidecar.stored_exclusions(_ALPHA) in ([], None)


@pytest.mark.asyncio
async def test_saved_exclusions_are_readable_back_through_codex_lb(async_client, sidecar, monkeypatch):
    """codex-lb reports the list it saved, so the editor is not locked or empty."""
    # CLIProxyAPI 7.2.135 omits the field from its auth-files listing, so codex-lb
    # reads it from the auth file and refuses paths outside the auth directory.
    # Point that guard at this run's synthetic directory, which is the auth
    # directory the sidecar under test was actually started with.
    monkeypatch.setattr(
        "app.modules.claude_sidecar.excluded_models.default_auth_dir",
        lambda: sidecar.auth_dir,
    )
    await _configure_codex_lb(async_client, sidecar.base_url)

    await _save_exclusions(async_client, _ALPHA, [_WILDCARD])

    response = await async_client.get("/api/claude-sidecar/routing")
    assert response.status_code == 200, response.text
    accounts = {account["name"]: account for account in response.json()["accounts"]}
    assert accounts[_ALPHA]["excludedModels"] == [_WILDCARD]
    assert accounts[_ALPHA]["excludedModelsState"] == "available"
    # The other account keeps its own independent, still-empty list.
    assert accounts[_BRAVO]["excludedModels"] == []
    assert accounts[_BRAVO]["excludedModelsState"] == "available"


@pytest.mark.asyncio
async def test_retry_never_falls_back_onto_the_excluded_account(async_client, sidecar):
    """Retry within one request does not undo the exclusion decision.

    Every attempt fails against the dead synthetic upstream, so CLIProxyAPI
    exhausts its in-request retry path. The excluded account must not be called
    on any hop, while a permitted model shows the retry path really does span
    both accounts, so the first assertion is not passing for lack of retries.
    """
    await _configure_codex_lb(async_client, sidecar.base_url)

    await _save_exclusions(async_client, _ALPHA, [_MODEL_EXACT])

    assert sidecar.accounts_called_for(_MODEL_EXACT) == {_BRAVO}
    assert sidecar.accounts_called_for(_MODEL_SIBLING) == {_ALPHA, _BRAVO}
    # This is the only test that sends model requests; prove they never left the
    # machine, so the selection evidence above is not live provider traffic.
    assert not sidecar.reached_a_provider()


@pytest.mark.asyncio
async def test_exclusion_holds_when_the_account_also_aliases_that_model(async_client, aliasing_sidecar):
    """An exclusion is not undone by a per-account alias for the same model.

    A per-account ``model_aliases`` entry renames a registered wire id, and
    selection matches the aliased id. Exclusion filters the catalog before the
    alias is applied, so an operator who excludes the underlying wire id must
    lose the aliased id on that account too, while the account without the
    exclusion keeps serving under the alias.
    """
    await _configure_codex_lb(async_client, aliasing_sidecar.base_url)

    await _save_exclusions(async_client, _ALPHA, [_MODEL_EXACT])

    alpha_models = aliasing_sidecar.models_for_account(_ALPHA)
    bravo_models = aliasing_sidecar.models_for_account(_BRAVO)
    assert _MODEL_EXACT not in alpha_models
    assert _ALIAS not in alpha_models
    assert _ALIAS in bravo_models
