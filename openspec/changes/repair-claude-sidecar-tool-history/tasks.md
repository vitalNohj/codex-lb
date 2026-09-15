## 1. Sidecar message repair

- [x] 1.1 Add `_repair_sidecar_unanswered_tool_calls` in `claude_sidecar_dispatch.py` and run it inside `sanitize_sidecar_chat_messages` after orphan filtering.
- [x] 1.2 Unit tests: aborted call, partially answered parallel calls, fully answered calls unchanged, trailing assistant tool call ends with the placeholder instead of a continuation.

## 2. Duplicate tool definitions

- [x] 2.1 Skip later duplicate wire names in `_map_tools_array` in `sidecar_tool_mapper.py`.
- [x] 2.2 Unit test: duplicate names collapse to the first definition; mapped-name uniqueness suffixing still works.

## 3. Route-level regression

- [x] 3.1 Integration test on `/v1/chat/completions` with the dangling-history shape proving the forwarded sidecar payload contains the placeholder tool message.
- [x] 3.2 Integration test on `/v1/chat/completions` with duplicate tool names proving the forwarded `tools` array is deduplicated.

## 4. Validation

- [x] 4.1 `openspec validate repair-claude-sidecar-tool-history --strict` and `openspec validate --specs`.
- [x] 4.2 `uv run ruff check`, `uv run ty check`, targeted `uv run pytest`.
