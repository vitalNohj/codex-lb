# Tasks

## 1. Sidecar message sanitization

- [x] 1.1 Add `sanitize_sidecar_chat_messages` and call it from
      `build_sidecar_chat_payload`.
- [x] 1.2 Unit tests: trailing assistant gets continuation user message,
      empty messages dropped, orphan tool messages dropped.

## 2. Verification

- [x] 2.1 `uv run pytest tests/unit/test_claude_sidecar_dispatch.py`
- [x] 2.2 `uv run ruff check` on touched files
- [x] 2.3 `openspec validate --strict`
