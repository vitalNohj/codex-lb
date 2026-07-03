## Why

Cursor's BYOK custom-model path sends `max_tokens: 4096` on every `/v1/chat/completions` agent turn. Claude sidecar models with heavy thinking (Fable 5, Opus 4.8 under a forced `xhigh` effort) can burn the entire 4096-token output budget on thinking alone, producing no usable content or complete tool calls. Cursor then retries ~every 60s with the same large context, creating a token-burn loop. ~19% of Claude sidecar requests over 14 days hit exactly 4096 output tokens. codex-lb currently forwards the client `max_tokens` unchanged.

## What Changes

- `build_sidecar_chat_payload()` (Claude sidecar chat-completions forward path) raises a client-supplied `max_tokens` (and `max_completion_tokens`) to a per-model floor and clamps it to the model's published maximum output.
- Floors/caps are keyed by the canonical Claude model (via `canonical_sidecar_model()`), starting conservative: 32k floor; 128k cap for Fable 5 / Opus 4.8, 64k cap for Haiku 4.5 / Sonnet 4.5.
- Requests without a client `max_tokens` are unchanged (no value injected). Models without a configured cap are unchanged.
- Native Codex Responses path, OpenRouter/OmniRoute/Ollama sidecars: untouched.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `chat-completions-compat`: Claude sidecar chat payloads gain a per-model output-token floor/cap applied to client-supplied `max_tokens` on every request.

## Impact

- Backend: `app/modules/proxy/claude_sidecar_dispatch.py` only.
- Tests: `tests/unit/test_claude_sidecar_dispatch.py`.
- No schema, settings, or frontend changes; no restart required by this change itself (backend restart applies it when the operator chooses).
