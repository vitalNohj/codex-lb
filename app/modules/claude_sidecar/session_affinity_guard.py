"""Warn when CLIProxyAPI's ``routing.session-affinity`` is off.

codex-lb pins a conversation to one credential by prefixing the model it sends
CLIProxyAPI. When routing fails open, or no credential is a candidate, the
model goes out unprefixed and CLIProxyAPI picks the credential itself. With
session affinity off it rotates per request, and since xAI and Anthropic cache
a prompt per account, every rotated turn is a full cache miss. Affinity is the
fallback that keeps those turns on one credential.

The switch belongs to the operator (the dashboard toggles it), so codex-lb
never flips it back on behind their back. It reports the state instead: a
gauge on every read, and a warning log when affinity goes off, repeated while
it stays off.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from app.core.clients.claude_sidecar import ClaudeSidecarClient
from app.core.metrics.prometheus import cliproxy_session_affinity_enabled

logger = logging.getLogger(__name__)

# How often an unchanged "off" is logged again.
SESSION_AFFINITY_WARNING_REPEAT_SECONDS = 3600.0


@dataclass(slots=True)
class _GuardState:
    last_enabled: bool | None = None
    last_warned_at: float | None = None


_STATE = _GuardState()


def reset_session_affinity_guard() -> None:
    _STATE.last_enabled = None
    _STATE.last_warned_at = None


async def check_cliproxy_session_affinity(client: ClaudeSidecarClient) -> bool | None:
    """Read the switch, publish it, and warn if it is off.

    Returns the state, or ``None`` when it could not be read. A failed read
    changes nothing and never fails the caller: the quota poll that makes it
    reports CLIProxyAPI's health and must go on.
    """

    try:
        enabled = await client.get_session_affinity()
    except Exception:
        logger.debug("could not read CLIProxyAPI routing.session-affinity", exc_info=True)
        return None
    observe_session_affinity(enabled)
    return enabled


def observe_session_affinity(enabled: bool, *, now: float | None = None) -> None:
    if cliproxy_session_affinity_enabled is not None:
        cliproxy_session_affinity_enabled.set(1 if enabled else 0)
    current = time.monotonic() if now is None else now
    previous = _STATE.last_enabled
    _STATE.last_enabled = enabled
    if enabled:
        if previous is False:
            logger.info("CLIProxyAPI routing.session-affinity is on again")
        _STATE.last_warned_at = None
        return
    if (
        previous is False
        and _STATE.last_warned_at is not None
        and current - _STATE.last_warned_at < SESSION_AFFINITY_WARNING_REPEAT_SECONDS
    ):
        return
    _STATE.last_warned_at = current
    logger.warning(
        "CLIProxyAPI routing.session-affinity is off: a conversation codex-lb cannot pin "
        "to a credential may move to another account on each turn and miss the upstream "
        "prompt cache. Turn session affinity on in the CLIProxyAPI routing settings."
    )
