"""Which inbound header carries the client's conversation id, per client agent.

Extracted from ``app/modules/proxy/_service/support.py`` so the request-log path
and the OpenCode Go outbound-session path read the *same* precedence chain
rather than two copies that can drift apart. ``support.py`` keeps its own thin
wrapper for the user-agent fields it also needs.

This lives in ``app/core`` rather than under the proxy module because
``app/core/clients`` needs it and core may not import from ``app/modules``.

The table is user-agent scoped on purpose. An OpenCode client pointed at
codex-lb under a provider id that does not start with ``opencode`` sends
``x-session-affinity``/``x-session-id`` rather than ``x-opencode-session``, and
both carry the same underlying session value - so the fallbacks are genuinely
the same conversation, not a guess. Scoping by agent is also what stops one
client's header name being read out of an unrelated client's request.
"""

from __future__ import annotations

from collections.abc import Mapping

#: Ordered ``(user-agent prefix, header names in precedence order)`` pairs. The
#: first matching user-agent prefix wins and its header list is searched in
#: order; no other agent's headers are consulted.
CONVERSATION_HEADERS_BY_USERAGENT_PREFIX: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("opencode", ("x-parent-session-id", "x-opencode-session", "x-session-id", "x-session-affinity")),
    ("codex", ("thread-id",)),
)


def client_agent_group(headers: Mapping[str, str]) -> str | None:
    """Return the matched user-agent prefix (``"opencode"``, ``"codex"``, ...).

    This is the *matched table key*, not the raw user agent, which is what makes
    it usable as a namespace: two builds of the same client agree, and an
    unrecognized client gets ``None`` rather than a value that varies per
    version string.
    """

    raw_useragent = next((value for key, value in headers.items() if key.lower() == "user-agent"), None)
    if raw_useragent is None:
        return None
    normalized = raw_useragent.strip().casefold()
    for prefix, _header_names in CONVERSATION_HEADERS_BY_USERAGENT_PREFIX:
        if normalized.startswith(prefix):
            return prefix
    return None


def extract_conversation_id(headers: Mapping[str, str]) -> str | None:
    """Return the client's own conversation id, or ``None``.

    Never infers one. A client that sends no recognized header has no
    conversation identity as far as codex-lb is concerned, and callers must
    handle that honestly rather than substituting a value.
    """

    raw_useragent = next((value for key, value in headers.items() if key.lower() == "user-agent"), None)
    if raw_useragent is None:
        return None
    normalized_useragent = raw_useragent.strip().casefold()
    normalized_headers = {key.casefold(): value for key, value in headers.items()}
    for prefix, header_names in CONVERSATION_HEADERS_BY_USERAGENT_PREFIX:
        if not normalized_useragent.startswith(prefix):
            continue
        for header_name in header_names:
            value = normalized_headers.get(header_name)
            if value and (conversation_id := value.strip()):
                return conversation_id
        # First matching agent wins outright: falling through to another agent's
        # header names would read a value this client never meant as a session.
        return None
    return None
