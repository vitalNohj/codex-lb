# Fix Claude Sidecar Cursor Message Sanitization

## Why

Cursor sends OpenAI chat-completions payloads to codex-lb that CLIProxyAPI
forwards to Anthropic using Claude OAuth tokens. OAuth-backed Claude models
reject assistant-message prefill and empty or mismatched tool-result turns.
codex-lb currently forwards Cursor payloads after tool-ID and tool-name
rewrites only, so Anthropic returns errors such as "This model does not
support assistant message prefill" and generic `invalid_request_error`
payload failures.

## What Changes

- Sanitize sidecar-forwarded `messages` before dispatch:
  - drop empty-content messages,
  - drop orphan `tool` messages whose `tool_call_id` is not referenced by a
    prior assistant `tool_calls` entry,
  - ensure the forwarded conversation ends with a `user` message by appending a
    minimal continuation user turn when the last message is `assistant`.
- Add unit tests at the sidecar dispatch path for the Cursor failure modes.

## Impact

- Affected spec: `chat-completions-compat`.
- Affected code: `app/modules/proxy/claude_sidecar_dispatch.py`,
  `tests/unit/test_claude_sidecar_dispatch.py`.
- No dashboard or schema changes.
