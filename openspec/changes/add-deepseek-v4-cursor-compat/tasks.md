# Tasks

## 1. Detection
- [x] 1.1 Add `is_deepseek_v4_model(model, aliases)` and `deepseek_v4_family_token(model, aliases)` helpers (case-insensitive, path-segment + `-`/`_` tolerant; alias exact match).
- [x] 1.2 Unit tests for detection: family tokens, provider-prefixed (`oc/deepseek-v4-flash-free`), `-`/`_` variants, alias match, and negatives (non-DeepSeek models).

## 2. Bounded reasoning cache
- [x] 2.1 Implement `DeepSeekReasoningCache` (LRU + TTL + maxsize, thread-safe, lazy expiry, swallow-and-log on error).
- [x] 2.2 Module-level singleton accessor; tests construct isolated instances.
- [x] 2.3 Unit tests: eviction by size, expiry by TTL, hit moves to MRU.

## 3. Cache key strategy
- [x] 3.1 Implement canonical conversation-prefix reducer (exclude `reasoning_content`; reduce messages to role/content/tool_calls/tool_call_id).
- [x] 3.2 Implement `reasoning_cache_key(prefix, provider, model_family, api_key_hash)` (SHA-256 hex).
- [x] 3.3 Unit tests: store-key (from response prefix + new assistant turn) equals lookup-key (from later request ending at same assistant turn); keys differ across provider / family / api key.

## 4. Request re-injection (outgoing)
- [x] 4.1 Implement `reinject_reasoning_into_sidecar_body(body, provider, model_family, api_key_hash, cache)` that patches assistant tool-call messages missing non-empty `reasoning_content`.
- [x] 4.2 Mutate only the sidecar body; leave the client payload untouched.
- [x] 4.3 Unit tests: re-injection patches the right message; missing-cache leaves body unchanged; already-present reasoning is not overwritten.

## 5. Non-streaming capture
- [x] 5.1 Implement `capture_reasoning_from_response(response_body, outgoing_messages, provider, model_family, api_key_hash, cache)` that stores reasoning when the response assistant message has `tool_calls`.
- [x] 5.2 Unit tests: stores reasoning keyed correctly; no-op when no tool_calls or no reasoning_content.

## 6. Streaming capture
- [x] 6.1 Implement `DeepSeekReasoningStreamObserver` wrapping an `AsyncIterator[bytes]`: pass-through all chunks, accumulate `delta.reasoning_content` + `delta.tool_calls`, detect clean `tool_calls` finish + `[DONE]`, commit on clean completion only.
- [x] 6.2 Unit tests: accumulates multi-chunk reasoning; commits on clean tool-call finish; does NOT commit on error/interrupt/non-tool finish; forwards every chunk unchanged (including error chunks).

## 7. Hook into sidecar dispatch
- [x] 7.1 In `proxy_chat_to_openrouter` and `proxy_chat_to_omniroute`: compute scope (model family + alias config + api key hash) once.
- [x] 7.2 Re-inject into the built sidecar body before sending (streaming + non-streaming).
- [x] 7.3 Non-streaming: capture from the successful response before the cursor-usage fallback runs.
- [x] 7.4 Streaming: wrap the raw sidecar byte stream with the observer ahead of the cursor-compat wrapper and keepalive injection; preserve provider iterator settlement/logging.
- [x] 7.5 Verify non-DeepSeek path is unchanged (scope gate returns early).

## 8. Optional alias config (defaults empty)
- [x] 8.1 Alias support is threaded through detection/scope as a parameter
  (`aliases: frozenset[str]`, empty default → no behavior change). Deferred: no
  DB settings field added yet (would require a migration); family-token
  detection already covers the configured `oc/deepseek-v4-flash-free` traffic.
- [x] 8.2 Aliases parameter plumbed into `resolve_scope` (dispatch passes the
  default empty set today; a settings-backed list can populate it later without
  contract changes).

## 9. Integration tests (dispatch path)
- [x] 9.1 Non-streaming repair end-to-end through `proxy_chat_to_omniroute` with a fake client.
- [x] 9.2 Streaming repair end-to-end (deltas → re-injection on next turn).
- [x] 9.3 Isolation across api key / provider / family.
- [x] 9.4 Missing-cache forwards unchanged.
- [x] 9.5 Cursor usage-fallback still applied for DeepSeek traffic.
- [x] 9.6 Non-DeepSeek pass-through unchanged (no capture/re-injection).

## 10. Validation
- [x] 10.1 `openspec validate add-deepseek-v4-cursor-compat --strict` clean.
- [x] 10.2 `uv run pytest` on the new tests passing.
- [x] 10.3 `uv run ruff` clean on changed files.
