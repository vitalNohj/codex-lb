# Tasks

## 1. Sidecar message sanitization

- [x] 1.1 Add `sanitize_sidecar_chat_messages` and call it from
      `build_sidecar_chat_payload`.
- [x] 1.2 Unit tests: trailing assistant gets continuation user message,
      empty messages dropped, orphan tool messages dropped.
- [x] 1.3 Accept Cursor-native `tool_result` content parts in chat requests and
      normalize them for the non-sidecar Responses path.
- [x] 1.4 Unit tests: Cursor-native `tool_result` parts are accepted, referenced
      parts keep sanitized IDs, and orphan parts are dropped before sidecar
      forwarding.
- [x] 1.5 Normalize Cursor-native sidecar tool history to OpenAI-compatible
      `tool_calls` and `tool` messages before forwarding to CLIProxyAPI.

## 2. Verification

- [x] 2.1 `uv run pytest tests/unit/test_claude_sidecar_dispatch.py tests/unit/test_openai_requests.py`
- [x] 2.2 `uv run ruff check` on touched files
- [x] 2.3 `openspec validate fix-claude-sidecar-cursor-message-sanitization --strict`
