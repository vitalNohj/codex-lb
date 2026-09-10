"""Focused outcomes for the legacy full-main fixture's startup generator."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

_LEGACY_FIXTURE = Path(__file__).parents[2] / "integration" / "test_claude_sidecar_excluded_models_contract.py"


class _FakeProcess:
    def __init__(self, *, returncode: int | None) -> None:
        self.returncode = returncode
        self.terminated = False
        self.killed = False
        self.wait_calls: list[int] = []

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, *, timeout: int) -> int:
        self.wait_calls.append(timeout)
        return self.returncode or 0


class _ReadyResponse:
    status_code = 200

    @staticmethod
    def json() -> dict[str, list[dict[str, str]]]:
        return {"files": [{"name": "alpha"}, {"name": "bravo"}]}


def _load_legacy_fixture() -> ModuleType:
    spec = importlib.util.spec_from_file_location("legacy_cliproxy_contract", _LEGACY_FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install_start_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    process: _FakeProcess,
    *,
    get: Any,
    monotonic: Any = lambda: 0.0,
) -> None:
    monkeypatch.setattr(module, "_binary", lambda: "/synthetic/cliproxy")
    monkeypatch.setattr(module, "_sandbox_exec", lambda: "/usr/bin/sandbox-exec")
    ports = iter((49152, 49153))
    monkeypatch.setattr(module, "_free_port", lambda: next(ports))
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(module.httpx, "get", get)
    monkeypatch.setattr(module.time, "monotonic", monotonic)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)


def _assert_startup_failure(generator: Any, message: str) -> None:
    try:
        with pytest.raises(pytest.fail.Exception, match=message):
            next(generator)
    except pytest.skip.Exception as error:
        pytest.fail(f"startup outcome was incorrectly reported as skip: {error}")


def test_start_sidecar_fails_when_configured_process_exits(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_legacy_fixture()
    process = _FakeProcess(returncode=17)
    _install_start_boundaries(monkeypatch, module, process, get=lambda *_args, **_kwargs: _ReadyResponse())

    generator = module._start_sidecar(tmp_path, None)
    _assert_startup_failure(generator, r"exited during startup with code 17")

    assert process.terminated
    assert process.wait_calls == [15]
    assert not process.killed


def test_start_sidecar_fails_when_readiness_times_out(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_legacy_fixture()
    process = _FakeProcess(returncode=None)
    times = iter((0.0, 61.0))

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise httpx.ConnectError("synthetic readiness refusal")

    _install_start_boundaries(monkeypatch, module, process, get=unavailable, monotonic=lambda: next(times))

    generator = module._start_sidecar(tmp_path, None)
    _assert_startup_failure(generator, "did not become ready within 60 seconds")

    assert process.terminated
    assert process.wait_calls == [15]
    assert not process.killed


def test_start_sidecar_yields_and_cleans_up_after_readiness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_legacy_fixture()
    process = _FakeProcess(returncode=None)
    _install_start_boundaries(monkeypatch, module, process, get=lambda *_args, **_kwargs: _ReadyResponse())

    generator = module._start_sidecar(tmp_path, None)
    sidecar = next(generator)
    assert sidecar.base_url == "http://127.0.0.1:49152"

    generator.close()
    assert process.terminated
    assert process.wait_calls == [15]
    assert not process.killed


def test_start_sidecar_still_skips_without_opt_in_binary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_legacy_fixture()
    monkeypatch.delenv("CODEX_LB_CLIPROXY_BINARY", raising=False)

    generator = module._start_sidecar(tmp_path, None)
    with pytest.raises(pytest.skip.Exception, match="set CODEX_LB_CLIPROXY_BINARY"):
        next(generator)
