"""Bounded model identities shared by native pricing and sidecar routing.

Do not add new substring globs to the legacy pricing alias table. These
version-specific identities must win over its older family-level aliases.
External integration prices remain owned by external_pricing catalogs.
"""

from __future__ import annotations

import re

_ASTRA_ID = re.compile(r"(?:(?:codex|openai)/)?gpt-6-astra(?:-\d{4}-\d{2}-\d{2}|-\d{8})?", re.IGNORECASE)
_FABLE_5_1_ID = re.compile(
    r"(?:^|[/:_-])claude-fable-5[.-]1"
    r"(?:-\d{8}|-\d{4}-\d{2}-\d{2})?"
    r"(?:-(?:thinking|reasoning))?"
    r"(?:-(?:none|auto|minimal|low|medium|high|xhigh|extra|max))?"
    r"(?:-(?:thinking|reasoning))?$",
    re.IGNORECASE,
)


def resolve_versioned_model_id(model: str) -> str | None:
    """Recognize supported versions without swallowing other family versions."""
    normalized = model.strip()
    if _ASTRA_ID.fullmatch(normalized):
        return "gpt-6-astra"
    if _FABLE_5_1_ID.search(normalized):
        return "claude-fable-5-1"
    return None
