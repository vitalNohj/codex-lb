## 1. Cache-write accounting

- [x] 1.1 Parse cache writes from CLIProxyAPI chat usage (non-streamed body, streamed `message_delta` and trailing usage chunks).
- [x] 1.2 Store `cache_write_input_tokens` on request logs with a migration; expose it in request-log schemas and the dashboard cost breakdown.
- [x] 1.3 Price writes at 2× the input rate; keep reads at the read rate and the remaining input at the input rate; keep zero-write totals bit-identical.

## 2. No untagged Claude requests

- [x] 2.1 Refuse a Claude model in `apply_cliproxy_account_route` when no prefixed credential is named (routing off, no candidate, selection failure); keep the plain-name fallback for other families.
- [x] 2.2 Answer `503 cliproxy_claude_route_unavailable`, release the reservation and log it; let poller holds answer first and retry the route after a near hold.

## 3. Byte-stable chat body

- [x] 3.1 Keep `reasoning_effort` at a fixed position under the operator override.
- [x] 3.2 Unit tests asserting every turn's wire body is the previous one plus appended messages (tools, effort, system prompt, metadata, derived cache key), with negative controls.
- [x] 3.3 Integration test: a Responses tool session reaches CLIProxyAPI append-only on one credential.

## 4. Direct-to-Anthropic

- [x] 4.1 Count pinned Claude turns with a cacheable prompt by cache hit or miss; warn on a miss, throttled per credential.
- [x] 4.2 Helm `CodexLBClaudeStickyCacheMiss` alert.
- [x] 4.3 Document the direct-to-`api.anthropic.com` requirement, the refusal, and cache-write pricing.
