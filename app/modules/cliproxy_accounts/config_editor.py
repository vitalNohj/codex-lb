"""Redact, restore, and diff CLIProxyAPI config.yaml without rewriting secrets.

The browser only ever sees a placeholder. A save that leaves that placeholder
in place splices the current secret back into the operator's YAML, so the
placeholder literal is never uploaded.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import dataclass

import yaml

REDACTION_MARK = "«codex-lb-redacted"
REDACTED_PLACEHOLDER = f"{REDACTION_MARK}»"
REDACTED_CHANGED = f"{REDACTION_MARK}:changed»"
_PLACEHOLDER_VALUES = frozenset({REDACTED_PLACEHOLDER, REDACTED_CHANGED})
_PLACEHOLDER_RE = re.compile(rf"^{re.escape(REDACTION_MARK)}:(\d+)»$")
_CHANGED_TOKEN = f'"{REDACTED_CHANGED}"'
_BLOCK_STYLES = frozenset({"|", ">"})

_MAX_BYTES = 1_000_000
_MAX_NODES = 10_000
_BOOL_TAG = "tag:yaml.org,2002:bool"
_NULL_TAG = "tag:yaml.org,2002:null"
_SECRET_PARTS = frozenset({"secret", "token", "password", "passwd", "credential", "apikey"})
_ICE_VALUE_KEYS = frozenset({"username", "credential", "password"})

type ConfigPath = tuple[str | int, ...]


class CliproxyConfigEditorError(ValueError):
    pass


class CliproxyConfigYamlError(CliproxyConfigEditorError):
    pass


class CliproxyConfigPlaceholderError(CliproxyConfigEditorError):
    pass


@dataclass(frozen=True, slots=True)
class _SecretSpan:
    path: ConfigPath
    start: int
    end: int
    value: str
    style: str | None


@dataclass(frozen=True, slots=True)
class ConfigEdit:
    restored: str
    diff: str
    changed: bool


def content_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def redact_config_yaml(text: str) -> str:
    """Return ``text`` with each secret replaced by its own numbered placeholder."""

    spans = _secret_spans(text)
    return _apply_replacements(
        text,
        [_span_replacement(text, span, _reference_token(index)) for index, span in enumerate(spans)],
    )


def prepare_config_edit(current: str | None, submitted: str) -> ConfigEdit:
    """Validate ``submitted`` and restore redacted secrets from ``current``.

    ``restored`` is the document to upload. ``diff`` compares redacted views, so
    a changed secret shows up as a placeholder change and the secret itself is
    absent from the diff.
    """

    current_text = current or ""
    if current_text:
        _secret_spans(current_text)
    restored = _restore(current_text, submitted)
    _assert_placeholder_not_written(current_text, restored)
    before = redact_config_yaml(current_text) if current_text else ""
    after = _diff_after(current_text, submitted)
    return ConfigEdit(restored=restored, diff=_unified_diff(before, after), changed=restored != current_text)


def routing_flags(text: str) -> tuple[bool | None, bool | None]:
    """Return ``(session-affinity, force-model-prefix)`` from a config document.

    A missing flag is the CLIProxyAPI default, false. A non-boolean value is
    reported as ``None`` so the panel does not guess.
    """

    try:
        root = _compose_mapping(text)
    except CliproxyConfigEditorError:
        return None, None
    routing = _child_mapping(root, "routing")
    if routing is None and not _has_key(root, "routing"):
        return False, False
    return _bool_at(routing, "session-affinity"), _bool_at(routing, "force-model-prefix")


def _restore(current: str, submitted: str) -> str:
    submitted_spans = _secret_spans(submitted)
    if not current:
        if any(
            _placeholder_reference(span.value) is not None or span.value in _PLACEHOLDER_VALUES
            for span in submitted_spans
        ):
            raise CliproxyConfigPlaceholderError("redacted placeholder has no existing secret to keep")
        return submitted

    originals = _secret_spans(current)
    replacements: list[tuple[int, int, str]] = []
    for span in submitted_spans:
        reference = _placeholder_reference(span.value)
        if reference is None and span.value not in _PLACEHOLDER_VALUES:
            continue
        if reference is None or reference >= len(originals):
            raise CliproxyConfigPlaceholderError(
                f"redacted placeholder has no existing secret to keep at {_format_path(span.path)}"
            )
        original = originals[reference]
        if not _may_restore(span.path, original.path):
            raise CliproxyConfigPlaceholderError(
                f"redacted placeholder cannot be moved onto {_format_path(span.path)}"
            )
        replacements.append((span.start, span.end, _restored_slice(current, original, submitted, span)))
    return _apply_replacements(submitted, replacements)


def _assert_placeholder_not_written(current: str, restored: str) -> None:
    if restored.count(REDACTION_MARK) > current.count(REDACTION_MARK):
        raise CliproxyConfigPlaceholderError("redacted placeholder cannot be written to the config file")
    for span in _secret_spans(restored):
        if _placeholder_reference(span.value) is not None or span.value in _PLACEHOLDER_VALUES:
            raise CliproxyConfigPlaceholderError("redacted placeholder cannot be written to the config file")


def _secret_spans(text: str) -> list[_SecretSpan]:
    root = _compose_mapping(text)
    spans: list[_SecretSpan] = []
    seen: set[int] = set()
    _walk(
        root,
        text,
        own_key=None,
        path=(),
        ancestors=(),
        secret_items=False,
        in_ice_server=False,
        spans=spans,
        seen=seen,
    )
    return spans


def _compose_mapping(text: str) -> yaml.MappingNode:
    _reject_size(text)
    try:
        documents = [document for document in yaml.compose_all(text, Loader=yaml.SafeLoader) if document is not None]
    except yaml.YAMLError as exc:
        raise _yaml_error(exc) from exc
    if len(documents) != 1 or not isinstance(documents[0], yaml.MappingNode):
        raise CliproxyConfigYamlError("config root must be a single YAML mapping")
    return documents[0]


def _walk(
    node: yaml.Node,
    text: str,
    *,
    own_key: str | None,
    path: ConfigPath,
    ancestors: tuple[str, ...],
    secret_items: bool,
    in_ice_server: bool,
    spans: list[_SecretSpan],
    seen: set[int],
) -> None:
    _visit(node, seen)
    if isinstance(node, yaml.ScalarNode):
        if node.tag != _NULL_TAG and isinstance(node.value, str) and _should_redact(
            own_key, node.value, ancestors, secret_items, in_ice_server
        ):
            start, end = _scalar_span(node)
            spans.append(_SecretSpan(path, start, end, node.value, node.style))
        return
    if isinstance(node, yaml.SequenceNode):
        items_are_secret = secret_items or (own_key is not None and _key_is_secret(own_key))
        parent_is_ice = own_key is not None and _normalize_key(own_key) == "ice-servers"
        for index, item in enumerate(node.value):
            item_is_mapping = isinstance(item, yaml.MappingNode)
            _walk(
                item,
                text,
                own_key=None if item_is_mapping else own_key,
                path=(*path, index),
                ancestors=ancestors,
                secret_items=items_are_secret and not item_is_mapping,
                in_ice_server=in_ice_server or (parent_is_ice and item_is_mapping),
                spans=spans,
                seen=seen,
            )
        return
    if isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            _visit(key_node, seen)
            if not isinstance(key_node, yaml.ScalarNode) or not isinstance(key_node.value, str):
                raise CliproxyConfigYamlError("YAML mapping keys must be strings")
            key = key_node.value
            _walk(
                value_node,
                text,
                own_key=key,
                path=(*path, key),
                ancestors=(*ancestors, key),
                secret_items=False,
                in_ice_server=in_ice_server,
                spans=spans,
                seen=seen,
            )
        return
    raise CliproxyConfigYamlError("unsupported YAML node")


def _should_redact(
    own_key: str | None,
    value: str,
    ancestors: tuple[str, ...],
    secret_items: bool,
    in_ice_server: bool,
) -> bool:
    if value == "":
        return False
    # A redacted URL no longer contains userinfo, so the placeholder itself has to
    # stay on the secret path or the original credential cannot be spliced back.
    if REDACTION_MARK in value:
        return True
    if _embeds_userinfo(value):
        return True
    if in_ice_server and own_key is not None and _normalize_key(own_key) in _ICE_VALUE_KEYS:
        return True
    if secret_items:
        return True
    if own_key is not None and _key_is_secret(own_key):
        return True
    return (
        own_key is not None
        and _normalize_key(own_key) == "key"
        and any(_key_is_secret(ancestor) for ancestor in ancestors)
    )


def _key_is_secret(key: str) -> bool:
    parts = set(_normalize_key(key).split("-"))
    if parts & _SECRET_PARTS:
        return True
    if "api" in parts and ({"key", "keys"} & parts):
        return True
    return "private" in parts and "key" in parts


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("_", "-")


def _embeds_userinfo(value: str) -> bool:
    if "://" in value:
        after_scheme = value.split("://", 1)[1]
        return "@" in after_scheme.split("/", 1)[0]
    if value.lower().startswith("turn:"):
        after_scheme = value[5:]
        return "@" in after_scheme.split("?", 1)[0]
    return False


def _scalar_span(node: yaml.ScalarNode) -> tuple[int, int]:
    start = node.start_mark
    end = node.end_mark
    if start is None or end is None:
        raise CliproxyConfigYamlError("YAML scalar is missing a source span")
    return start.index, end.index


def _visit(node: yaml.Node, seen: set[int]) -> None:
    if id(node) in seen:
        raise CliproxyConfigYamlError("YAML anchors are not supported in the config editor")
    seen.add(id(node))
    if len(seen) > _MAX_NODES:
        raise CliproxyConfigYamlError("YAML document is too large")


def _reject_size(text: str) -> None:
    if len(text.encode("utf-8")) > _MAX_BYTES:
        raise CliproxyConfigYamlError("YAML document is too large")


def _reference_token(index: int) -> str:
    return f'"{REDACTION_MARK}:{index}»"'


def _placeholder_reference(value: str) -> int | None:
    match = _PLACEHOLDER_RE.fullmatch(value.strip("\r\n"))
    if match is None:
        return None
    return int(match.group(1))


def _may_restore(destination: ConfigPath, original: ConfigPath) -> bool:
    return destination == original or _path_is_secret_destination(destination)


def _path_is_secret_destination(path: ConfigPath) -> bool:
    if not path:
        return False
    if isinstance(path[-1], int):
        owner = _sequence_owner(path)
        return owner is not None and _key_is_secret(owner)
    own_key = path[-1]
    if not isinstance(own_key, str):
        return False
    if _key_is_secret(own_key):
        return True
    if _normalize_key(own_key) in _ICE_VALUE_KEYS and _path_in_ice_server(path):
        return True
    ancestors = tuple(part for part in path[:-1] if isinstance(part, str))
    return _normalize_key(own_key) == "key" and any(_key_is_secret(ancestor) for ancestor in ancestors)


def _sequence_owner(path: ConfigPath) -> str | None:
    index = len(path) - 1
    while index >= 0 and isinstance(path[index], int):
        index -= 1
    owner = path[index] if index >= 0 else None
    return owner if isinstance(owner, str) else None


def _path_in_ice_server(path: ConfigPath) -> bool:
    for index, part in enumerate(path):
        if isinstance(part, str) and _normalize_key(part) == "ice-servers" and index + 1 < len(path):
            if isinstance(path[index + 1], int):
                return True
    return False


def _restored_slice(current: str, original: _SecretSpan, submitted: str, destination: _SecretSpan) -> str:
    body = _original_slice(current, original)
    if destination.style not in _BLOCK_STYLES:
        return body
    breaks = _trailing_break_length(submitted, destination)
    return body + submitted[destination.end - breaks : destination.end]


def _span_replacement(text: str, span: _SecretSpan, token: str) -> tuple[int, int, str]:
    breaks = _trailing_break_length(text, span) if span.style in _BLOCK_STYLES else 0
    return span.start, span.end, token + text[span.end - breaks : span.end]


def _original_slice(text: str, span: _SecretSpan) -> str:
    breaks = _trailing_break_length(text, span) if span.style in _BLOCK_STYLES else 0
    return text[span.start : span.end - breaks]


def _trailing_break_length(text: str, span: _SecretSpan) -> int:
    index = span.end
    while index > span.start and text[index - 1] == "\n":
        index -= 1
        if index > span.start and text[index - 1] == "\r":
            index -= 1
    if index <= span.start:
        return 0
    return span.end - index


def _diff_after(current: str, submitted: str) -> str:
    if not current:
        return redact_config_yaml(submitted)
    spans = _secret_spans(submitted)
    return _apply_replacements(
        submitted,
        [
            _span_replacement(submitted, span, _CHANGED_TOKEN)
            for span in spans
            if _placeholder_reference(span.value) is None and span.value not in _PLACEHOLDER_VALUES
        ],
    )


def _apply_replacements(text: str, replacements: list[tuple[int, int, str]]) -> str:
    unique: list[tuple[int, int, str]] = []
    seen: set[tuple[int, int]] = set()
    for start, end, replacement in replacements:
        if (start, end) in seen:
            continue
        seen.add((start, end))
        unique.append((start, end, replacement))
    unique.sort(key=lambda item: item[0], reverse=True)
    cursor: int | None = None
    for start, end, replacement in unique:
        if cursor is not None and end > cursor:
            raise CliproxyConfigYamlError("overlapping secret values")
        cursor = start
        text = text[:start] + replacement + text[end:]
    return text


def _unified_diff(before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="current",
            tofile="proposed",
        )
    )


def _child_mapping(root: yaml.MappingNode, key: str) -> yaml.MappingNode | None:
    for key_node, value_node in root.value:
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
            if isinstance(value_node, yaml.MappingNode):
                return value_node
            return None
    return None


def _has_key(root: yaml.MappingNode, key: str) -> bool:
    return any(isinstance(key_node, yaml.ScalarNode) and key_node.value == key for key_node, _value in root.value)


def _bool_at(mapping: yaml.MappingNode | None, key: str) -> bool | None:
    if mapping is None:
        return None
    for key_node, value_node in mapping.value:
        if not isinstance(key_node, yaml.ScalarNode) or key_node.value != key:
            continue
        if not isinstance(value_node, yaml.ScalarNode) or value_node.tag != _BOOL_TAG:
            return None
        if value_node.value == "true":
            return True
        if value_node.value == "false":
            return False
        return None
    return False


def _format_path(path: ConfigPath) -> str:
    rendered = ""
    for part in path:
        if isinstance(part, int):
            rendered += f"[{part}]"
        elif rendered:
            rendered += f".{part}"
        else:
            rendered = part
    return rendered or "<root>"


def _yaml_error(exc: yaml.YAMLError) -> CliproxyConfigYamlError:
    mark = getattr(exc, "problem_mark", None)
    if mark is not None:
        return CliproxyConfigYamlError(f"Invalid YAML at line {mark.line + 1}, column {mark.column + 1}")
    return CliproxyConfigYamlError("Invalid YAML")
