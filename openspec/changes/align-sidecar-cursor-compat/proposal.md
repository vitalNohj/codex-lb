## Why

Cursor-compatible clients rely on codex-lb's upstream-style Chat Completions compatibility to receive usable usage metadata and synthetic high-usage compaction signals when an upstream context limit is reached. The native `/v1/chat/completions` path already applies that shared behavior, but sidecar routing drifted into provider-specific Cursor handling: Claude has a duplicate stream usage rewriter, while OpenRouter and OmniRoute request usage from their OpenAI-compatible providers without applying the shared Cursor fallback and streamed context-limit handling.

CLIProxyAPI, OpenRouter, and OmniRoute already produce OpenAI chat-completions shaped responses for their sidecar paths. codex-lb should treat those outputs as OpenAI chat streams and apply the same Cursor compatibility layer used by the native chat path, while keeping only provider-specific fixes that sidecars cannot know about.

## What Changes

- Add one shared Cursor OpenAI chat SSE compatibility wrapper for usage fallback and streamed context-limit synthetic usage.
- Apply the shared Cursor wrapper to Cursor-compatible sidecar chat streams after provider-specific stream cleanup.
- Remove Claude's sidecar-specific Cursor usage rewriter while preserving Claude tool-name and tool-ID compatibility.
- Pass Cursor compatibility state into OpenRouter and OmniRoute chat sidecar dispatchers.
- Apply shared non-stream usage fallback to sidecar chat responses only for Cursor-compatible clients.
- Add regression coverage for valid usage forwarding, missing usage fallback, streamed context-limit compaction signals, and non-Cursor pass-through.

## Non-goals

- Do not redesign Cursor compaction behavior.
- Do not change model routing order or model access rules.
- Do not change CLIProxyAPI, OpenRouter, or OmniRoute translation behavior.
- Do not change context-window advertisement unless a separate test proves metadata is wrong.
- Do not remove Claude-specific tool-name, tool-ID, or message-shape compatibility.

## Capabilities

### Modified Capabilities

- `chat-completions-compat`: Cursor-compatible sidecar streams use the same usage fallback and context-limit synthetic usage semantics as native Cursor chat completions.

## Impact

- Cursor compatibility logic in `app/modules/proxy/cursor_chat_compat.py`.
- Sidecar dispatch flow in `app/modules/proxy/claude_sidecar_dispatch.py`, `app/modules/proxy/openrouter_sidecar_dispatch.py`, and `app/modules/proxy/omniroute_sidecar_dispatch.py`.
- Chat completions routing in `app/modules/proxy/api.py`.
- Integration tests for Claude, OpenRouter, OmniRoute, and native Chat Completions Cursor behavior.
