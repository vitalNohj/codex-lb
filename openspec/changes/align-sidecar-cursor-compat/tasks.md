## 1. OpenSpec artifacts

- [x] 1.1 Create proposal, tasks, and chat-completions-compat delta spec.
- [x] 1.2 Validate the OpenSpec change locally.

## 2. Shared Cursor stream wrapper

- [x] 2.1 Replace the Claude-specific Cursor SSE usage rewriter with a provider-neutral Cursor chat SSE compatibility rewriter.
- [x] 2.2 Make the shared rewriter buffer complete SSE events, preserve non-data SSE fields where possible, and expose terminal state after synthetic context-limit replacement.
- [x] 2.3 Reuse the existing Cursor prompt/completion token estimation and context-length error predicates.

## 3. Sidecar adoption

- [x] 3.1 Update Claude streaming so Claude tool-name rewriting runs before the shared Cursor wrapper.
- [x] 3.2 Pass Cursor compatibility state into OpenRouter and OmniRoute chat sidecar dispatchers.
- [x] 3.3 Apply the shared Cursor wrapper to OpenRouter and OmniRoute streams only for Cursor-compatible clients.
- [x] 3.4 Apply non-stream Cursor usage fallback to OpenRouter and OmniRoute responses only for Cursor-compatible clients.

## 4. Regression tests

- [x] 4.1 Add or update Claude sidecar tests for valid usage pass-through, missing usage fallback, streamed context-limit synthetic usage, and non-Cursor pass-through.
- [x] 4.2 Add OpenRouter sidecar tests for missing usage fallback, streamed context-limit synthetic usage, and non-Cursor pass-through.
- [x] 4.3 Add OmniRoute sidecar tests for missing usage fallback, streamed context-limit synthetic usage, and non-Cursor pass-through.
- [x] 4.4 Confirm native Cursor chat-completions context-limit tests still pass.

## 5. Verification

- [x] 5.1 Run focused Claude, OpenRouter, OmniRoute, and native Chat Completions tests.
- [x] 5.2 Run Ruff on touched files.
- [x] 5.3 Run IDE lint checks on touched files.
- [x] 5.4 Run `openspec validate align-sidecar-cursor-compat --strict`.
