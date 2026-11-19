"""Adopt a listening socket that systemd holds across service restarts.

With a ``codex-lb.socket`` unit, systemd owns the listening socket for the
whole life of the socket unit and passes it to every new service process
(``sd_listen_fds`` protocol: ``LISTEN_PID``/``LISTEN_FDS``, descriptors from
fd 3). Connections that arrive while one process drains and the next one
starts wait in the kernel accept queue instead of being refused.
"""

from __future__ import annotations

import os
import socket

SD_LISTEN_FDS_START = 3

_LISTEN_ENV_KEYS = ("LISTEN_PID", "LISTEN_FDS", "LISTEN_FDNAMES")


class SocketActivationError(RuntimeError):
    """systemd passed descriptors that this server cannot serve on."""


def inherited_listen_socket() -> socket.socket | None:
    """Return the one listening TCP socket systemd passed to this process.

    Returns ``None`` when systemd passed no descriptors to this process. The
    ``LISTEN_*`` variables are removed either way, so a child process never
    mistakes them for its own (``sd_listen_fds(unset_environment=1)``).
    """
    listen_pid = os.environ.get("LISTEN_PID")
    listen_fds = os.environ.get("LISTEN_FDS")
    for key in _LISTEN_ENV_KEYS:
        os.environ.pop(key, None)
    if listen_pid is None or listen_fds is None:
        return None
    try:
        addressed_pid = int(listen_pid)
        fd_count = int(listen_fds)
    except ValueError as exc:
        raise SocketActivationError(
            f"systemd socket activation variables are not integers (LISTEN_PID={listen_pid!r}, "
            f"LISTEN_FDS={listen_fds!r})"
        ) from exc
    if addressed_pid != os.getpid():
        # The variables belong to an ancestor (for example a wrapper that
        # forked this process); its descriptors are not ours to adopt.
        return None
    if fd_count == 0:
        return None
    if fd_count != 1:
        raise SocketActivationError(f"systemd passed {fd_count} sockets; codex-lb serves exactly one listening socket")
    try:
        sock = socket.socket(fileno=SD_LISTEN_FDS_START)
    except OSError as exc:
        raise SocketActivationError(f"fd {SD_LISTEN_FDS_START} from systemd is not a socket: {exc}") from exc
    if sock.type != socket.SOCK_STREAM or sock.family not in (socket.AF_INET, socket.AF_INET6):
        sock.detach()
        raise SocketActivationError(
            f"systemd socket must be a TCP stream socket (family={sock.family!r}, type={sock.type!r})"
        )
    if not sock.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN):
        sock.detach()
        raise SocketActivationError("systemd socket is not listening")
    # Native egress helpers start subprocesses; they must not inherit the
    # listening socket and keep it alive after this process exits.
    sock.set_inheritable(False)
    return sock


def socket_port(sock: socket.socket) -> int:
    return int(sock.getsockname()[1])
