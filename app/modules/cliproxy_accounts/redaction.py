"""Strip credential material from text that can reach the panel or the audit log."""

from __future__ import annotations

import re

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(access_token|refresh_token|id_token|api_key|authorization|device_code|client_secret|code)\b"
    r"\s*[:=]\s*\S+"
)
_BEARER = re.compile(r"(?i)\bBearer\s+\S+")
_MAX_PUBLIC_MESSAGE = 300


def public_message(message: str) -> str:
    """Return a short message safe to show in the panel."""

    cleaned = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[redacted]", message)
    cleaned = _BEARER.sub("Bearer [redacted]", cleaned)
    cleaned = cleaned.strip()
    if len(cleaned) <= _MAX_PUBLIC_MESSAGE:
        return cleaned
    return cleaned[: _MAX_PUBLIC_MESSAGE - 1] + "…"
