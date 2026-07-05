## Why

Cursor's BYOK custom-model path sends `max_tokens: 4096` on every `/v1/chat/completions` agent turn. Claude sidecar models with heavy thinking (Fable 5, Opus 4.8 under a forced `xhigh` effort) can burn the entire 4096-token output budget on thinking alone, producing no usable content or complete tool calls. Cursor then retries ~every 60s with the same large context, creating a token-burn loop. ~19% of Claude sidecar requests over 14 days hit exactly 4096 output tokens. codex-lb currently forwards the client `max_tokens` unchanged.

## What Changes

- `build_sidecar_chat_payload()` (Claude sidecar chat-completions forward path) raises a client-supplied `max_tokens` (and `max_completion_tokens`) to a per-model floor and clamps it to the model's published maximum output.
- Bounds are keyed by the canonical Claude model (via `canonical_sidecar_model()`) with a 32k floor and authoritative per-model caps (128k for Fable 5 / Opus 4.6–4.8 / Sonnet 5; 64k for Sonnet 4.5/4.6 and Haiku 4.5; 32k for Opus 4.5), sourced from Anthropic's models overview and cross-checked against OmniRoute's model-capability registry (which applies the same class of thinking-aware output-token buffer).
- A context-window guard lowers the raise when estimated input plus `max_tokens` would exceed the model window (protecting the 200k-context models), but never below the client's original request.
- Requests without a client `max_tokens` are unchanged (no value injected). Models without configured bounds are unchanged.
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
