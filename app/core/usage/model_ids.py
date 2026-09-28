"""Bounded model identities shared by native pricing and sidecar routing.

Do not add substring globs for Claude model families. Prefixes, release
dates, and reasoning-effort suffixes peel off the same id; a longer id is
not a shorter family. External integration prices remain owned by
external_pricing catalogs.
"""

from __future__ import annotations

import re

_GPT6_NATIVE_ID = re.compile(
    r"(?:(?:codex|openai)/)?gpt-6-(astra|sol|luna)(?:-\d{4}-\d{2}-\d{2}|-\d{8})?",
    re.IGNORECASE,
)
_FABLE_5_1_ID = re.compile(
    r"(?:^|[/:_-])claude-fable-5[.-]1"
    r"(?:-\d{8}|-\d{4}-\d{2}-\d{2})?"
    r"(?:-(?:thinking|reasoning))?"
    r"(?:-(?:none|auto|minimal|low|medium|high|xhigh|extra|max))?"
    r"(?:-(?:thinking|reasoning))?$",
    re.IGNORECASE,
)
# Bare id, or a prefix this proxy actually routes: cc/, cp-, cp_.
# A single separator such as "-" would also accept not-claude-opus-5-5
# and not-claude-sonnet-5-5.
_OPUS_5_5_ID = re.compile(
    r"^(?:cc/|cp[-_])?claude-opus-5[.-]5"
    r"(?:-\d{8}|-\d{4}-\d{2}-\d{2})?"
    r"(?:-(?:thinking|reasoning))?"
    r"(?:-(?:none|auto|minimal|low|medium|high|xhigh|extra|max))?"
    r"(?:-(?:thinking|reasoning))?$",
    re.IGNORECASE,
)
_SONNET_5_5_ID = re.compile(
    r"^(?:cc/|cp[-_])?claude-sonnet-5[.-]5"
    r"(?:-\d{8}|-\d{4}-\d{2}-\d{2})?"
    r"(?:-(?:thinking|reasoning))?"
    r"(?:-(?:none|auto|minimal|low|medium|high|xhigh|extra|max))?"
    r"(?:-(?:thinking|reasoning))?$",
    re.IGNORECASE,
)


_EFFORT_TOKENS = frozenset({"none", "auto", "minimal", "low", "medium", "high", "xhigh", "extra", "max"})
_MARKER_TOKENS = frozenset({"thinking", "reasoning"})
_TRAILING_RELEASE_DATE = re.compile(r"-(?:\d{8}|\d{4}-\d{2}-\d{2})$", re.IGNORECASE)
_KNOWN_SIDECAR_PREFIXES = ("cc/", "cp-", "cp_")


def resolve_versioned_model_id(model: str) -> str | None:
    """Recognize supported versions without swallowing other family versions."""
    normalized = model.strip()
    native = _GPT6_NATIVE_ID.fullmatch(normalized)
    if native is not None:
        return f"gpt-6-{native.group(1).lower()}"
    if _FABLE_5_1_ID.search(normalized):
        return "claude-fable-5-1"
    if _OPUS_5_5_ID.search(normalized):
        return "claude-opus-5-5"
    if _SONNET_5_5_ID.search(normalized):
        return "claude-sonnet-5-5"
    return None


def strip_known_sidecar_prefix(model: str) -> str:
    """Remove one leading ``cc/``, ``cp-``, or ``cp_`` routing prefix."""
    lowered = model.lower()
    for prefix in _KNOWN_SIDECAR_PREFIXES:
        if lowered.startswith(prefix):
            return model[len(prefix) :]
    return model


def _peel_trailing_token(model: str, allowed: frozenset[str]) -> tuple[str, str] | None:
    head, separator, token = model.rpartition("-")
    if not separator or not head:
        return None
    normalized = token.lower()
    if normalized not in allowed:
        return None
    return head, normalized


def split_model_effort_suffix(model: str) -> tuple[str, str | None]:
    """Split one trailing effort token and any adjacent thinking marker.

    ``claude-opus-4-7-thinking-high`` becomes ``claude-opus-4-7`` and
    ``high``. A lone ``-thinking`` tail is left in place. ``extra`` is
    returned as ``xhigh``.
    """
    base = model
    peeled_marker = _peel_trailing_token(base, _MARKER_TOKENS)
    if peeled_marker is not None:
        base = peeled_marker[0]
    peeled_effort = _peel_trailing_token(base, _EFFORT_TOKENS)
    if peeled_effort is None:
        return model, None
    base, effort = peeled_effort
    peeled_marker = _peel_trailing_token(base, _MARKER_TOKENS)
    if peeled_marker is not None:
        base = peeled_marker[0]
    if not base:
        return model, None
    if effort == "extra":
        effort = "xhigh"
    return base, effort


def strip_trailing_release_date(model: str) -> str:
    """Remove one trailing ``-YYYYMMDD`` or ``-YYYY-MM-DD`` release stamp."""
    match = _TRAILING_RELEASE_DATE.search(model)
    if match is None:
        return model
    body = model[: match.start()]
    return body or model


def claude_model_identity(model: str) -> str:
    """The Claude id after prefix, effort, and release-date decoration is removed.

    A versioned identity (Fable 5.1, Opus 5.5, Sonnet 5.5) wins so dotted
    forms collapse to the hyphenated key. Other ids keep every remaining
    token, including a longer sibling of a priced family.
    """
    stripped = strip_known_sidecar_prefix(model.strip())
    if not stripped:
        return model.strip()
    versioned = resolve_versioned_model_id(stripped)
    if versioned is not None and versioned.lower().startswith("claude-"):
        return versioned
    base, _effort = split_model_effort_suffix(stripped)
    return strip_trailing_release_date(base)
