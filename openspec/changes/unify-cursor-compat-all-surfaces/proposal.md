## Why

Cursor only compacts a conversation when the proxy reports over-limit usage on
a successful turn. codex-lb already does that, but only on
`POST /v1/chat/completions`. Cursor's Responses traffic (`POST /v1/responses`
and `POST /backend-api/codex/responses`) never went through the Cursor layer,
so a context-length failure reached Cursor as a plain error envelope or
`response.failed` and compaction never fired.

That gap is endpoint-shaped, not model-shaped, so it silently widens whenever a
model moves to a path the layer does not cover. Cursor traffic for
`gpt-5.6-sol` is 100 percent native Responses, so the entire compaction
mechanism was inert for it; the same hole applied to `gpt-5.5` on Responses.

Two smaller holes existed on the chat path itself: a late (post-startup)
non-stream context error returned an error envelope instead of the synthetic
completion, and only the Claude sidecar converted non-stream context-length
failures, while OpenRouter, OmniRoute, and Ollama returned raw provider errors.

## What Changes

- Detect Cursor-compatible clients on the Responses entrypoints using the same
  single detector the chat path uses, and apply the same context-length
  compaction semantics there.
- Convert Responses context-length failures for Cursor-compatible clients into
  a successful Responses turn carrying synthetic over-limit usage, covering the
  startup-error path, mid-stream `response.failed`, and the non-stream
  collected paths.
- Convert late non-stream context-length errors on `POST /v1/chat/completions`
  into the existing synthetic chat completion.
- Share one context-length detector across all sidecar providers and apply the
  synthetic chat completion to non-stream context-length failures for
  OpenRouter, OmniRoute, and Ollama, matching the Claude sidecar.
- Keep behavior for non-Cursor clients unchanged on every touched path.

## Impact

- Affected specs: `chat-completions-compat`, `responses-api-compat`.
- Affected code: `app/modules/proxy/cursor_chat_compat.py`,
  `app/modules/proxy/api.py`, `app/modules/proxy/claude_sidecar_dispatch.py`,
  `app/modules/proxy/openrouter_sidecar_dispatch.py`,
  `app/modules/proxy/omniroute_sidecar_dispatch.py`,
  `app/modules/proxy/ollama_sidecar_dispatch.py`,
  `tests/integration/test_proxy_responses.py`.
- No database, settings, or dashboard changes.
- HTTP bridge internals and the Codex compact endpoints are intentionally
  untouched; see `design.md`.
