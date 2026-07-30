# Tasks

## 1. Shared Cursor policy helpers

- [x] 1.1 Add Responses-shaped synthetic over-limit payload, JSON response, and SSE event builders to `cursor_chat_compat.py`.
- [x] 1.2 Add `stream_responses_with_cursor_context_limit_fallback` to rewrite Responses context-length failure events into the synthetic completion, preserving the upstream response id and avoiding a duplicate `response.created`.
- [x] 1.3 Add shared `is_sidecar_context_length_error` and route the Claude sidecar helper through it.

## 2. Responses entrypoints

- [x] 2.1 Detect Cursor-compatible clients in `_stream_responses` and `_collect_responses` with the existing detector.
- [x] 2.2 Convert Cursor context-length startup errors in `_stream_responses` into the synthetic Responses stream.
- [x] 2.3 Wrap the public Responses stream with the Cursor context-limit fallback for Cursor-compatible clients.
- [x] 2.4 Convert Cursor context-length failures in `_collect_responses` for the raised-error, `status == "failed"`, and error-envelope paths.
- [x] 2.5 Leave HTTP bridge internals and Codex compact endpoints untouched; conversion happens at the API response boundary only.

## 3. Chat and sidecar holes

- [x] 3.1 Convert late non-stream Cursor context-length errors on `/v1/chat/completions` into the synthetic chat completion.
- [x] 3.2 Add the Cursor non-stream context-length branch to the OpenRouter sidecar dispatch.
- [x] 3.3 Add the Cursor non-stream context-length branch to the OmniRoute sidecar dispatch.
- [x] 3.4 Add the Cursor non-stream context-length branch to the Ollama sidecar dispatch.

## 4. Tests

- [x] 4.1 Add streaming Responses Cursor context-limit tests parametrized across multiple models including `gpt-5.6-sol`.
- [x] 4.2 Add non-streaming Responses Cursor context-limit tests parametrized across the same models.
- [x] 4.3 Add non-Cursor Responses tests proving context-length failures stay unchanged for streaming and non-streaming.
- [x] 4.4 Add a `/backend-api/codex/responses` Cursor test covering the second Responses route.
- [x] 4.5 Confirm existing Cursor chat and sidecar suites still pass.

## 5. GPT-5.6 Cursor success-path proactive compaction

- [x] 5.1 Detect `gpt-5.6-*` chat usage at/above `350_000` prompt tokens and rewrite to synthetic `1_000_000` for Cursor chat handlers.
- [x] 5.2 Cover helper, non-stream apply paths, and streaming usage-chunk rewrite with unit tests.
- [x] 5.3 Add OpenSpec delta for proactive Sol compaction (error-path-only for non-gpt-5.6).

## 6. Validation

- [x] 6.1 `uv run ruff check app/modules/proxy tests/integration/test_proxy_responses.py`.
- [x] 6.2 `uv run pytest tests/integration/test_proxy_responses.py tests/integration/test_http_responses_bridge.py tests/integration/test_api_keys_api.py`.
- [x] 6.3 `uv run pytest tests/integration/test_proxy_chat_completions.py tests/integration/test_claude_sidecar_routing.py tests/integration/test_openrouter_sidecar_routing.py tests/integration/test_omniroute_sidecar_routing.py`.
- [x] 6.4 `openspec validate unify-cursor-compat-all-surfaces --strict`.
- [x] 6.5 `uv run pytest tests/unit/test_cursor_proactive_compaction.py`.
