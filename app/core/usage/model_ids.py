"""Bounded model identities shared by native pricing and sidecar routing.

Routing prefixes are not model ids. ``cc/``, ``cp-``, and ``cp_`` peel off so
a logged client id can find the same price key the router forwarded. A dotted
spelling, a release date, and an effort suffix are different ids. Do not add
substring globs for Claude model families. External integration prices remain
owned by external_pricing catalogs.
"""

from __future__ import annotations

import re

_GPT6_NATIVE_ID = re.compile(
    r"(?:(?:codex|openai)/)?gpt-6-(astra|sol|luna)(?:-\d{4}-\d{2}-\d{2}|-\d{8})?",
    re.IGNORECASE,
)

_KNOWN_SIDECAR_PREFIXES = ("cc/", "cp-", "cp_")


def resolve_versioned_model_id(model: str) -> str | None:
    """Recognize supported native versions without swallowing other ids."""
    native = _GPT6_NATIVE_ID.fullmatch(model.strip())
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
