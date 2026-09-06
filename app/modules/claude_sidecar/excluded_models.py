"""Per-account CLIProxyAPI model exclusion lists.

CLIProxyAPI stores an ``excluded_models`` list on each auth file and skips that
credential when a requested wire model matches one of its patterns. codex-lb
reads and writes that list verbatim: it is opaque operator data, never a
per-account or per-model branch in Python.

CLIProxyAPI 7.2.135 accepts the field on ``PATCH /v0/management/auth-files/fields``
but omits it from the auth-files listing, so the read path falls back to opening
the auth file named by the listing entry's ``path`` and copying only that one
key. Nothing else from that file - tokens above all - is returned or logged.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_PATTERN_LENGTH = 128
MAX_PATTERNS = 32

# A comma can never appear inside a single pattern: CLIProxyAPI stores the
# per-account list as a comma-joined attribute and splits it on "," at routing
# time, so an embedded comma would silently split one pattern into two bogus
# ones.
_FORBIDDEN_CHARACTERS = ("\n", "\r", "\x00", ",")
_SNAKE_KEY = "excluded_models"
_KEBAB_KEY = "excluded-models"


def default_auth_dir() -> Path:
    """Return the CLIProxyAPI auth directory that auth-file paths must sit under."""
    return Path.home() / ".cli-proxy-api"


def normalize_excluded_models(raw: object) -> list[str]:
    """Return a clean, bounded model-exclusion list from arbitrary input.

    Non-string entries are dropped. Remaining entries are trimmed, then dropped
    when empty, when they contain a newline, NUL, or comma, or when they exceed
    ``MAX_PATTERN_LENGTH``. Duplicates are removed case-insensitively keeping the
    first spelling, at most ``MAX_PATTERNS`` entries survive, and input order is
    preserved.
    """
    if not isinstance(raw, Iterable) or isinstance(raw, str | bytes | Mapping):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, str):
            continue
        pattern = entry.strip()
        if not pattern or len(pattern) > MAX_PATTERN_LENGTH:
            continue
        if any(char in pattern for char in _FORBIDDEN_CHARACTERS):
            continue
        key = pattern.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(pattern)
        if len(normalized) >= MAX_PATTERNS:
            break
    return normalized


def excluded_models_from_mapping(entry: Mapping[str, object]) -> list[str]:
    """Return the normalized exclusion list carried by an auth-file mapping."""
    if _SNAKE_KEY in entry:
        return normalize_excluded_models(entry[_SNAKE_KEY])
    if _KEBAB_KEY in entry:
        return normalize_excluded_models(entry[_KEBAB_KEY])
    return []


def excluded_models_from_auth_file(path: str | None, auth_dir: Path | None = None) -> list[str]:
    """Return the normalized exclusion list stored in an auth file on disk.

    Returns an empty list when the path is absent, resolves outside the
    CLIProxyAPI auth directory, is missing, or does not parse as a JSON object.
    Only the exclusion key is read out of the file; no other key is returned or
    logged.
    """
    if not isinstance(path, str) or not path.strip():
        return []
    root = (auth_dir or default_auth_dir()).expanduser()
    try:
        resolved = Path(path).expanduser().resolve()
        root_resolved = root.resolve()
    except OSError:
        logger.warning("could not resolve CLIProxyAPI auth-file path")
        return []
    if not resolved.is_relative_to(root_resolved):
        logger.warning("refusing to read CLIProxyAPI auth-file outside the auth directory")
        return []
    try:
        parsed = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        logger.warning("could not read CLIProxyAPI auth-file excluded models")
        return []
    if not isinstance(parsed, Mapping):
        return []
    return excluded_models_from_mapping(parsed)


def excluded_models_for_entry(entry: Mapping[str, object], auth_dir: Path | None = None) -> list[str]:
    """Return an auth entry's exclusion list, reading its file only when needed."""
    if _SNAKE_KEY in entry or _KEBAB_KEY in entry:
        return excluded_models_from_mapping(entry)
    path = entry.get("path")
    return excluded_models_from_auth_file(path if isinstance(path, str) else None, auth_dir)
