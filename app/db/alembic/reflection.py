"""Reflection hook for Alembic migration runs.

SQLite cannot alter a column in place, so ``batch_alter_table`` reflects the
table and recreates it. SQLAlchemy wraps each reflected server default string
in ``text()``, and ``text()`` reads ``:name`` as a bind parameter. A JSON
default such as ``dashboard_settings.dashboard_layout_json``
(``{"requests":true,...}``) then comes back from the rebuild as
``{"requests"NULL,...}``. Any later batch migration on that table would corrupt
the default this way, including migrations that never touch the column.

The hook is scoped to the migration run. Schema drift checks reflect the same
tables and compare the default text, so they must see it unescaped.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Table, event, text
from sqlalchemy.dialects import sqlite
from sqlalchemy.engine.reflection import Inspector

# ``text()``'s bind-parameter pattern (``TextClause._bind_params_regex``).
_TEXT_BIND_RE = re.compile(r"(?<![:\w\\]):(\w+)(?!:)")
# A backslash-colon, which the compiler unescapes to a bare colon.
_ESCAPED_COLON_RE = re.compile(r"\\(?=:)")


def _rendered(default: str) -> str:
    return str(text(default).compile(dialect=sqlite.dialect()))


def _escaped(default: str) -> str:
    return _TEXT_BIND_RE.sub(r"\\:\1", _ESCAPED_COLON_RE.sub(r"\\\\", default))


def escape_reflected_default_binds(inspector: Inspector, table: Table, column_info: dict[str, Any]) -> None:
    """Make a reflected default render byte-identical when the table is rebuilt."""

    del inspector, table
    default = column_info.get("default")
    # Stays a string: Alembic's own SQLite reflect hook inspects it as one.
    if not isinstance(default, str) or ":" not in default or _rendered(default) == default:
        return
    candidate = _escaped(default)
    # Only a form that compiles back to the stored text is safe to hand on;
    # anything else keeps SQLAlchemy's behaviour unchanged.
    if _rendered(candidate) == default:
        column_info["default"] = candidate


@contextmanager
def reflected_default_escaping() -> Iterator[None]:
    """Escape reflected defaults for the duration of one migration run."""

    if event.contains(Table, "column_reflect", escape_reflected_default_binds):
        yield
        return
    event.listen(Table, "column_reflect", escape_reflected_default_binds)
    try:
        yield
    finally:
        event.remove(Table, "column_reflect", escape_reflected_default_binds)
