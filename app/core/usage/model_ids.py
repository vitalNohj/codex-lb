"""Bounded model identities shared by native pricing and sidecar routing.

Routing prefixes are not model ids. ``cc/``, ``cp-``, and ``cp_`` peel off so
a logged client id can find the same price key the router forwarded. Dotted
spellings, release dates, and effort suffixes remain distinct Claude ids.
Configured native spellings are bounded by the model catalog. Do not add
substring globs for Claude model families. External integration prices remain
owned by external_pricing catalogs.
"""

from __future__ import annotations

import re

from app.core.models.local import load_local_catalog

_NATIVE_PREFIX_RE = re.compile(r"^(?:codex|openai)/", re.IGNORECASE)
_RELEASE_RE = re.compile(r"(?:-\d{4}-\d{2}-\d{2}|-\d{8})$")

_KNOWN_SIDECAR_PREFIXES = ("cc/", "cp-", "cp_")


def resolve_versioned_model_id(model: str) -> str | None:
    """Recognize configured native spellings without peeling a routing prefix.

    Authorization has already resolved its wire id. A remaining sidecar prefix
    belongs to that id and must not be removed for a second time.
    """
    text = _NATIVE_PREFIX_RE.sub("", model.strip()).lower()
    models = load_local_catalog().models
    base = _RELEASE_RE.sub("", text)
    entry = models.get(base)
    if entry is not None and entry.native_aliases:
        return base
    for canonical, entry in models.items():
        if not entry.native_aliases:
            continue
        for suffix in entry.native_suffixes:
            ending = "-" + suffix
            if text.endswith(ending) and _RELEASE_RE.sub("", text[: -len(ending)]) == canonical:
                return canonical
    return None


def strip_known_sidecar_prefix(model: str) -> str:
    """Remove one leading ``cc/``, ``cp-``, or ``cp_`` routing prefix."""
    lowered = model.lower()
    for prefix in _KNOWN_SIDECAR_PREFIXES:
        if lowered.startswith(prefix):
            return model[len(prefix) :]
    return model
