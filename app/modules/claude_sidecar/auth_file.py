"""Path-confined reads of non-secret keys from CLIProxyAPI auth files.

CLIProxyAPI's auth-files listing leaves out metadata that the auth file itself
stores: ``excluded_models`` (7.2.135) and ``prefix`` (still absent in 8.0.36).
codex-lb reads such a key from the file named by the listing entry's ``path``.

The file also holds the credential's tokens. Every caller of ``read_auth_file``
copies out only the one key it needs, and nothing here logs the parsed file. A
path must resolve inside the CLIProxyAPI auth directory, after following
symlinks; any other path is refused, not read.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from pathlib import Path

logger = logging.getLogger(__name__)

_PREFIX_KEY = "prefix"


def default_auth_dir() -> Path:
    """Return the CLIProxyAPI auth directory that auth-file paths must sit under."""
    return Path.home() / ".cli-proxy-api"


def read_auth_file(path: str | None, auth_dir: Path | None = None) -> Mapping[str, object] | None:
    """Parse one auth file inside ``auth_dir``, or return ``None``.

    ``auth_dir`` defaults to ``default_auth_dir()``. ``None`` means the file
    cannot be read: the path is absent, resolves outside the auth directory, is
    missing, or does not parse as a JSON object. The returned mapping holds
    tokens; callers take only the key they need from it.
    """
    if not isinstance(path, str) or not path.strip():
        return None
    try:
        resolved = Path(path).expanduser().resolve()
        root_resolved = (auth_dir or default_auth_dir()).expanduser().resolve()
    except OSError:
        logger.warning("could not resolve CLIProxyAPI auth-file path")
        return None
    if not resolved.is_relative_to(root_resolved):
        logger.warning("refusing to read CLIProxyAPI auth-file outside the auth directory")
        return None
    try:
        parsed = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        logger.warning("could not read CLIProxyAPI auth-file")
        return None
    if not isinstance(parsed, Mapping):
        return None
    return parsed


def stored_prefix_for_entry(entry: Mapping[str, object], auth_dir: Path | None = None) -> str | None:
    """Return the prefix CLIProxyAPI stores for one auth-file listing entry.

    A non-empty ``prefix`` in the listing entry wins. Otherwise the prefix is
    read from the auth file on disk. ``None`` means no prefix was found: the
    file stores none, or it cannot be read.
    """
    listed = _text(entry.get(_PREFIX_KEY))
    if listed is not None:
        return listed
    path = entry.get("path")
    stored = read_auth_file(path if isinstance(path, str) else None, auth_dir)
    if stored is None:
        return None
    return _text(stored.get(_PREFIX_KEY))


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None
