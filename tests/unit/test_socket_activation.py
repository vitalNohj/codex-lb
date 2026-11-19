from __future__ import annotations

import os
import socket
from collections.abc import Iterator

import pytest

from app.core import socket_activation
from app.core.socket_activation import SocketActivationError, inherited_listen_socket

pytestmark = pytest.mark.unit


@pytest.fixture
def fd3_slot() -> Iterator[None]:
    """Free fd 3 for the test and restore whatever the runner had there."""
    saved: int | None
    try:
        saved = os.dup(socket_activation.SD_LISTEN_FDS_START)
    except OSError:
        saved = None
    try:
        yield
    finally:
        if saved is not None:
            os.dup2(saved, socket_activation.SD_LISTEN_FDS_START)
            os.close(saved)
        else:
            try:
                os.close(socket_activation.SD_LISTEN_FDS_START)
            except OSError:
                pass


def _place_on_fd3(sock: socket.socket) -> None:
    os.dup2(sock.fileno(), socket_activation.SD_LISTEN_FDS_START)
    sock.close()


def _set_listen_env(monkeypatch: pytest.MonkeyPatch, *, pid: int, fds: int) -> None:
    monkeypatch.setenv("LISTEN_PID", str(pid))
    monkeypatch.setenv("LISTEN_FDS", str(fds))
    monkeypatch.setenv("LISTEN_FDNAMES", "codex-lb.socket")


def test_no_systemd_environment_means_no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("LISTEN_PID", "LISTEN_FDS", "LISTEN_FDNAMES"):
        monkeypatch.delenv(key, raising=False)

    assert inherited_listen_socket() is None


def test_variables_for_another_process_are_ignored_and_cleared(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_listen_env(monkeypatch, pid=os.getpid() + 1, fds=1)

    assert inherited_listen_socket() is None
    assert "LISTEN_PID" not in os.environ
    assert "LISTEN_FDS" not in os.environ
    assert "LISTEN_FDNAMES" not in os.environ


def test_adopts_the_listening_tcp_socket_on_fd3(monkeypatch: pytest.MonkeyPatch, fd3_slot: None) -> None:
    del fd3_slot
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    _place_on_fd3(listener)
    _set_listen_env(monkeypatch, pid=os.getpid(), fds=1)

    sock = inherited_listen_socket()

    assert sock is not None
    try:
        assert sock.fileno() == socket_activation.SD_LISTEN_FDS_START
        assert socket_activation.socket_port(sock) == port
        assert sock.get_inheritable() is False
        assert "LISTEN_PID" not in os.environ
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            accepted, _ = sock.accept()
            accepted.close()
    finally:
        sock.detach()


def test_refuses_a_socket_that_is_not_listening(monkeypatch: pytest.MonkeyPatch, fd3_slot: None) -> None:
    del fd3_slot
    unbound = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _place_on_fd3(unbound)
    _set_listen_env(monkeypatch, pid=os.getpid(), fds=1)

    with pytest.raises(SocketActivationError, match="not listening"):
        inherited_listen_socket()


def test_refuses_more_than_one_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_listen_env(monkeypatch, pid=os.getpid(), fds=2)

    with pytest.raises(SocketActivationError, match="exactly one"):
        inherited_listen_socket()


def test_refuses_malformed_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LISTEN_PID", "self")
    monkeypatch.setenv("LISTEN_FDS", "1")

    with pytest.raises(SocketActivationError, match="not integers"):
        inherited_listen_socket()
