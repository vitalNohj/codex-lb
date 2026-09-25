## Why

The Claude sidecar raises every client `max_tokens` below 32,768 up to 32,768 so thinking-heavy models cannot spend a small agent budget on thinking alone. Prompt-cache keep-warm replays deliberately ask for almost no output: pi's built-in `cacheWarming` and the `pi-keepwarm` extension re-send the last request with `max_tokens: 1` so the provider only reads the cached prefix and resets its lifetime. The floor turns each refresh into a full answer. A live `max_tokens: 1` request to `cc/claude-opus-5-5` returned 81 completion tokens instead of 1, so keep-warm pays for whole replies instead of a cache read.

## What Changes

- A client-supplied `max_tokens` or `max_completion_tokens` at or below 16 is forwarded unchanged instead of being raised to the model floor. 16 covers a 1-token keep-warm cap and the 16-token minimum OpenAI Responses callers send. Real agent turns send thousands of tokens, so they keep the floor.
- Values above 16 keep the existing floor, cap, and context-window guard.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `chat-completions-compat`: Claude sidecar chat payloads forward a minimal output cap unchanged.

## Impact

- Backend: `app/modules/proxy/claude_sidecar_dispatch.py` only.
- Tests: `tests/unit/test_claude_sidecar_dispatch.py`.
- No schema, settings, or frontend changes.
