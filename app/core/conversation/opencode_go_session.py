"""Outbound ``x-opencode-session`` identity for the OpenCode Go provider only.

OpenCode Go asks clients to "send a stable session ID in ``x-opencode-session``
for each conversation so we can optimize routing and prompt caching"
(https://opencode.ai/docs/go). Stability is the entire point: the value is a
cache-affinity key, so an id that changes every request is worse than no id at
all - it forfeits the affinity while looking to an operator as though the
obligation were met.

Resolution, in order:

1. The client already sent ``x-opencode-session`` itself. It is speaking Go's
   protocol directly, so the value is forwarded verbatim. Rewriting a client's
   own session id would split one conversation across two upstream cache keys.
2. codex-lb extracted a conversation id from the client's own headers via the
   shared user-agent-scoped table. That raw value is namespaced by the matched
   client agent and hashed to an opaque ``ses_`` token. Same conversation gives
   the same token on every turn; two different agents that happen to reuse the
   same raw id stay isolated; the raw identifier never leaves the process.
3. Nothing identifiable. **No header is sent**, and the documented consequence
   is that Go sees unknown identity and this request gets no prompt-cache
   affinity. That is the honest outcome.

Explicitly rejected alternatives, and why:

* A fresh random id per request. It satisfies a header presence check and
  nothing else: every request becomes its own conversation upstream.
* A content-derived fingerprint over model, system prompt and first user
  message. It collides across genuinely distinct conversations that share a
  preamble - the normal case for a coding agent, which is exactly the traffic
  Go is for - and it derives a stable upstream identifier from prompt content.

Scope is a hard constraint, not a convention. This resolution runs only on the
OpenCode Go dispatch path, so a client session identifier can never be handed to
an unrelated upstream.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from app.core.conversation.headers import client_agent_group, extract_conversation_id

#: The header Go documents. Also the header a Go-native client sends inbound.
OPENCODE_SESSION_HEADER = "x-opencode-session"

#: Prefix for a derived (hashed) identifier, so an upstream-visible value is
#: distinguishable from a client's own verbatim id.
_DERIVED_PREFIX = "ses_"

#: Hex characters kept from the SHA-256 digest. 32 hex chars is 128 bits, far
#: beyond collision range for a per-account conversation keyspace.
_DERIVED_HEX_LENGTH = 32

#: Upper bound on a verbatim client value we will forward. Long enough for any
#: UUID or opaque token in practice; bounded so a hostile or broken client
#: cannot push an unbounded header at the upstream through us. A longer value is
#: hashed rather than dropped, so the conversation keeps a stable identity.
_MAX_FORWARDED_LENGTH = 200

#: Namespace for a client whose agent the shared table does not recognize but
#: which nonetheless supplied a conversation id.
_GENERIC_AGENT = "generic"


def _derive_session_id(agent: str, raw_conversation_id: str) -> str:
    """Hash an agent-namespaced conversation id into an opaque ``ses_`` token.

    Namespacing before hashing is what keeps two clients isolated: a raw id that
    both happen to use (a bare counter, a reused UUID) maps to two different
    upstream identities rather than silently sharing one conversation's cache.

    Hashing hides the client's raw identifier from the upstream. It does not
    make the conversation unlinkable to them - it cannot, since the whole point
    is that the same conversation is recognizable across turns.
    """

    material = f"{agent}\x1f{raw_conversation_id}".encode("utf-8")
    digest = hashlib.sha256(material).hexdigest()[:_DERIVED_HEX_LENGTH]
    return f"{_DERIVED_PREFIX}{digest}"


def resolve_opencode_go_session_id(headers: Mapping[str, str]) -> str | None:
    """Resolve the outbound session id for one OpenCode Go request.

    Returns ``None`` when the client supplied nothing identifiable. Never
    raises: session derivation must not be able to fail a request.
    """

    try:
        normalized = {key.casefold(): value for key, value in headers.items()}

        direct = normalized.get(OPENCODE_SESSION_HEADER)
        if direct is not None:
            trimmed = direct.strip()
            # A blank or over-long direct header is not forwarded *verbatim*:
            # an empty value is not a session, and truncating an over-long one
            # would invent an identifier the client never used. An over-long
            # value is still a real conversation id, so it falls through to
            # derivation below, which bounds the length while keeping the value
            # stable across turns. A blank one carries no identity and falls
            # through to whatever other header the client supplied.
            if trimmed and len(trimmed) <= _MAX_FORWARDED_LENGTH:
                return trimmed

        raw_conversation_id = extract_conversation_id(headers)
        if not raw_conversation_id:
            return None
        return _derive_session_id(client_agent_group(headers) or _GENERIC_AGENT, raw_conversation_id)
    except Exception:
        return None


def apply_opencode_go_session_header(
    request_headers: dict[str, str],
    client_headers: Mapping[str, str] | None,
) -> dict[str, str]:
    """Return ``request_headers`` with the session header set when resolvable.

    Assignment is ``[key] =``, never an append, so a header mapping reused
    across requests cannot accumulate stale session values. The input mapping is
    not mutated.

    ``request_headers`` is always this integration's own header dict, built from
    stored configuration. No inbound header is ever merged into it, so a caller
    cannot reach ``Authorization`` or ``Host`` through this path.
    """

    headers = dict(request_headers)
    if client_headers is None:
        return headers
    session_id = resolve_opencode_go_session_id(client_headers)
    if session_id:
        headers[OPENCODE_SESSION_HEADER] = session_id
    return headers
