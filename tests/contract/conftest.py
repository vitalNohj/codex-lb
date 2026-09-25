"""Keep opt-in contracts out of an ordinary ``pytest tests`` run.

``cliproxy_exclusions/http`` runs only under its launcher (``run.sh``), which
builds a real CLIProxyAPI fixture, installs a private environment, and passes
``CODEX_LB_HTTP_FIXTURE_BASE_URL`` and ``CODEX_LB_HTTP_FIXTURE_AUTH_DIR``.
Outside it the test cannot run, so it is skipped with a pointer to the launcher
instead of failing on the missing variables.

The skip lives here rather than in the test file on purpose: ``run.sh`` pins
the SHA-256 of ``test_http_roundtrip.py`` and runs pytest with
``--confcutdir`` at that directory, so this conftest is never loaded there and
the pinned file stays byte-identical. The same holds when that directory is
passed to pytest directly: its own ``pytest.ini`` becomes the rootdir, so that
invocation is the launcher's configuration, not the suite's.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_HTTP_CONTRACT_DIR = Path(__file__).parent / "cliproxy_exclusions" / "http"
_FIXTURE_ENV = ("CODEX_LB_HTTP_FIXTURE_BASE_URL", "CODEX_LB_HTTP_FIXTURE_AUTH_DIR")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if all(os.environ.get(name) for name in _FIXTURE_ENV):
        return
    skip = pytest.mark.skip(
        reason=(
            "opt-in CLIProxyAPI HTTP contract: run tests/contract/cliproxy_exclusions/http/run.sh "
            f"(sets {' and '.join(_FIXTURE_ENV)})"
        )
    )
    for item in items:
        if item.path.is_relative_to(_HTTP_CONTRACT_DIR):
            item.add_marker(skip)
