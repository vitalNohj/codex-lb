from __future__ import annotations

import re

_ROUTING_HEADER = re.compile(r"^routing:[ \t]*(?:#.*)?$")
_AFFINITY_LINE = re.compile(
    r"^(?P<indent>[ \t]+)session-affinity:[ \t]*(?P<value>\S+)(?P<trail>[ \t]*#.*)?[ \t]*$"
)


class CliproxyRoutingConfigError(ValueError):
    pass


def apply_session_affinity_yaml(text: str, enabled: bool) -> str:
    """Set top-level ``routing.session-affinity`` without rewriting the rest of the file.

    A missing flag is already off, so requesting false leaves the document unchanged.
    An inline ``routing`` value is rejected so the caller does not upload a damaged file.
    """

    desired = "true" if enabled else "false"
    lines = text.splitlines(keepends=True)
    routing_at = _find_routing_block(lines)
    if routing_at is None:
        if not enabled:
            return text
        return _append_routing_block(text, desired)

    block_end, child_indent = _routing_block_end(lines, routing_at)
    for index in range(routing_at + 1, block_end):
        content = lines[index].rstrip("\r\n")
        if content.lstrip().startswith("#"):
            continue
        match = _AFFINITY_LINE.match(content)
        if match is None or match.group("indent") != child_indent:
            continue
        if match.group("value").lower() == desired:
            return text
        ending = lines[index][len(content) :]
        trail = match.group("trail") or ""
        lines[index] = f"{match.group('indent')}session-affinity: {desired}{trail}{ending}"
        return "".join(lines)

    if not enabled:
        return text
    ending = _line_ending(lines[routing_at])
    if not lines[routing_at].endswith(("\n", "\r")):
        lines[routing_at] += ending
    lines.insert(routing_at + 1, f"{child_indent}session-affinity: {desired}{ending}")
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


def _append_routing_block(text: str, desired: str) -> str:
    ending = "\r\n" if "\r\n" in text else "\n"
    base = text
    if base and not base.endswith(("\n", "\r")):
        base += ending
    return f"{base}routing:{ending}  session-affinity: {desired}{ending}"


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return "\n"
