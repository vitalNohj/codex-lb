from __future__ import annotations

import re

_ROUTING_HEADER = re.compile(r"^routing:[ \t]*(?:#.*)?$")
ROUTING_BOOL_FIELDS = frozenset({"session-affinity", "force-model-prefix"})
_FLAG_LINE = {
    field: re.compile(rf"^(?P<indent>[ \t]+){re.escape(field)}:[ \t]*(?P<value>\S+)(?P<trail>[ \t]*#.*)?[ \t]*$")
    for field in ROUTING_BOOL_FIELDS
}


class CliproxyRoutingConfigError(ValueError):
    pass


def apply_session_affinity_yaml(text: str, enabled: bool) -> str:
    """Set top-level ``routing.session-affinity`` without rewriting the rest of the file.

    A missing flag is already off, so requesting false leaves the document unchanged.
    An inline ``routing`` value is rejected so the caller does not upload a damaged file.
    """

    return apply_routing_bool_yaml(text, "session-affinity", enabled)


def apply_routing_bool_yaml(text: str, field: str, enabled: bool) -> str:
    """Set one top-level ``routing`` boolean without rewriting the rest of the file.

    A missing flag is already off, so requesting false leaves the document unchanged.
    An inline ``routing`` value is rejected so the caller does not upload a damaged file.
    ``field`` is limited to ``session-affinity`` and ``force-model-prefix``.
    """

    if field not in ROUTING_BOOL_FIELDS:
        raise CliproxyRoutingConfigError(f"unsupported CLIProxyAPI routing field: {field}")
    desired = "true" if enabled else "false"
    lines = text.splitlines(keepends=True)
    routing_at = _find_routing_block(lines)
    if routing_at is None:
        if not enabled:
            return text
        return _append_routing_block(text, field, desired)

    flag_line = _FLAG_LINE[field]
    block_end, child_indent = _routing_block_end(lines, routing_at)
    for index in range(routing_at + 1, block_end):
        content = lines[index].rstrip("\r\n")
        if content.lstrip().startswith("#"):
            continue
        match = flag_line.match(content)
        if match is None or match.group("indent") != child_indent:
            continue
        if match.group("value").lower() == desired:
            return text
        ending = lines[index][len(content) :]
        trail = match.group("trail") or ""
        lines[index] = f"{match.group('indent')}{field}: {desired}{trail}{ending}"
        return "".join(lines)

    if not enabled:
        return text
    ending = _line_ending(lines[routing_at])
    if not lines[routing_at].endswith(("\n", "\r")):
        lines[routing_at] += ending
    lines.insert(routing_at + 1, f"{child_indent}{field}: {desired}{ending}")
    return "".join(lines)


def _find_routing_block(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        content = line.rstrip("\r\n")
        if content.startswith((" ", "\t")) or content.strip() == "" or content.lstrip().startswith("#"):
            continue
        if not content.startswith("routing:"):
            continue
        if _ROUTING_HEADER.match(content):
            return index
        raise CliproxyRoutingConfigError("CLIProxyAPI routing section is not a block")
    return None


def _routing_block_end(lines: list[str], routing_at: int) -> tuple[int, str]:
    child_indent = "  "
    block_end = len(lines)
    saw_child = False
    for index in range(routing_at + 1, len(lines)):
        content = lines[index].rstrip("\r\n")
        if content.strip() == "" or content.lstrip().startswith("#"):
            continue
        if content[0] not in " \t":
            block_end = index
            break
        if not saw_child:
            saw_child = True
            child_indent = content[: len(content) - len(content.lstrip(" \t"))]
    return block_end, child_indent


def _append_routing_block(text: str, field: str, desired: str) -> str:
    ending = "\r\n" if "\r\n" in text else "\n"
    base = text
    if base and not base.endswith(("\n", "\r")):
        base += ending
    return f"{base}routing:{ending}  {field}: {desired}{ending}"


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return "\n"
