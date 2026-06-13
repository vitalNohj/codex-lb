## 1. Advertise the sidecar context window

- [x] 1.1 Add a helper that builds the capability/context fields (`context_length`, `contextLength`, `capabilities.context_length`) for sidecar models using a default 200000 window.
- [x] 1.2 Merge those fields into the Claude, OpenRouter, and OmniRoute sidecar entries when building `GET /v1/models`.

## 2. Cover the regression

- [x] 2.1 Extend the Claude, OpenRouter, and OmniRoute model-list integration tests to assert the sidecar entry exposes `context_length=200000` (and the capabilities mirror).
- [x] 2.2 Add coverage proving Cursor-compatible chat-completions requests use the default API-key reservation instead of pre-reserving the full large prompt estimate.
- [x] 2.3 Add coverage proving late Cursor-compatible context-limit stream errors are converted to synthetic usage instead of error chunks.

## 3. Validate the change

- [ ] 3.1 Run focused OpenSpec validation and the targeted `/v1/models` + sidecar routing tests.
