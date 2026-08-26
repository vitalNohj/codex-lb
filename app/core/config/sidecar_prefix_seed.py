"""One definition of how operator-configured prefixes become the stored seed.

The fresh-install seed is written from two places - the Alembic migration that
creates ``dashboard_settings`` and ``SettingsRepository.get_or_create`` for a row
the migration did not create - and the two must agree. In particular an
explicitly emptied ``CODEX_LB_*_MODEL_PREFIXES`` has to stay empty on both, since
clearing it is the escape hatch for an operator whose other integration already
owns that prefix and prefix uniqueness is enforced regardless of enabled state.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

# Stored column shape, mirroring ``parse_sidecar_prefixes``: a prefix ending in
# ``-`` or ``_`` is an alias that is stripped from the forwarded wire model, any
# other prefix is forwarded unchanged.
_STRIPPING_SUFFIXES = ("-", "_")


def dump_configured_sidecar_prefixes(prefixes: Iterable[str]) -> str:
    """Serialize configured prefix strings into the stored ``[{prefix, strip}]`` JSON."""

    seeded: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in prefixes:
        normalized = raw.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        seeded.append({"prefix": normalized, "strip": normalized.endswith(_STRIPPING_SUFFIXES)})
    return json.dumps(seeded, separators=(",", ":"))
