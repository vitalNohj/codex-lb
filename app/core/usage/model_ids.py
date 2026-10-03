"""Bounded model identities shared by native pricing and sidecar routing.

Routing prefixes are not model ids. ``cc/``, ``cp-``, and ``cp_`` peel off so
a logged client id can find the same price key the router forwarded. A dotted
spelling, a release date, and an effort suffix are different ids. Do not add
substring globs for Claude model families. A model the built-in pricing table
lists has that one price on every path, native or sidecar. Only an id the table
does not list is priced from the external_pricing catalogs.
"""

from __future__ import annotations

import re

_GPT6_NATIVE_ID = re.compile(
    r"(?:(?:codex|openai)/)?gpt-6-(astra|sol|luna)(?:-\d{4}-\d{2}-\d{2}|-\d{8})?",
    re.IGNORECASE,
)
# ``gpt-6.1-sol`` is a different model from ``gpt-6-sol``. The dot keeps the
# older matcher from treating 6.1 as a dated or suffixed 6 Sol id.
_GPT61_SOL_ID = re.compile(
    r"(?:(?:codex|openai)/)?gpt-6\.1-sol(?:-\d{4}-\d{2}-\d{2}|-\d{8})?",
    re.IGNORECASE,
)

_KNOWN_SIDECAR_PREFIXES = ("cc/", "cp-", "cp_")


def resolve_versioned_model_id(model: str) -> str | None:
    """Recognize supported native versions without swallowing other ids."""
    text = model.strip()
    if _GPT61_SOL_ID.fullmatch(text) is not None:
        return "gpt-6.1-sol"
    native = _GPT6_NATIVE_ID.fullmatch(text)
    if native is None:
        return None
    return f"gpt-6-{native.group(1).lower()}"


def strip_known_sidecar_prefix(model: str) -> str:
    """Remove one leading ``cc/``, ``cp-``, or ``cp_`` routing prefix."""
    lowered = model.lower()
    for prefix in _KNOWN_SIDECAR_PREFIXES:
        if lowered.startswith(prefix):
            return model[len(prefix) :]
    return model
