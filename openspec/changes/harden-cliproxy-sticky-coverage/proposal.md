# Keep CLIProxyAPI conversations on one credential

## Why

The reliability audit of the CLIProxyAPI capacity router (PR #145) found that many conversations never stick to one credential. Anthropic, OpenAI and the other providers behind CLIProxyAPI keep a separate prompt cache for each credential, so every switch rewrites the whole prefix at write prices instead of reading it.

On main `ddc34b715`, against a real CLIProxyAPI v8 binary and a cache-simulating upstream:
- chat requests with no `prompt_cache_key` or Codex session header alternated credentials every turn;
- `/v1/responses` requests that reached the chat bridge lost their `prompt_cache_key` in translation and alternated too;
- concurrent first turns of one conversation split across credentials, and the last writer won the pin;
- one transient 429 moved the pin for good, so the conversation never went back to its warm credential;
- expired pins were never deleted;
- unmeasured credentials scored as fully used and were starved;
- none of this was visible in logs or metrics.

## What Changes

- **Session identity (S1).** The router reads the conversation identity in CLIProxyAPI's order:
  1. body `prompt_cache_key`;
  2. Codex turn-state and session headers;
  3. `X-Claude-Code-Session-Id`, `X-Session-Id`, `X-Session-Affinity` and `X-<vendor>-Session-Id` headers;
  4. body `session_id`, `metadata.session_id` or `sessionId`;
  5. a content-derived key. It uses the Codex path's `_derive_prompt_cache_key` recipe: model class, API key, instructions and the first user/system content.

  Content that cannot be hashed stays unpinned rather than getting a random key. `X-Client-Request-Id` is per request and is not a session.
- **Responses bridge (S2/T1).** `responses_to_chat_request` forwards `prompt_cache_key`. When the client sent none, one is derived before translation. A derived key ranks below explicit session headers, so a compacted Codex history does not move the pin.
- **Observability (S3).** Every route decision increments `codex_lb_cliproxy_route_outcome_total{outcome,key_source}` and logs `cliproxy_route_outcome outcome=… key_source=…`. Outcomes are `selected`, `sticky`, `rebind`, `unpinned_no_key`, `fail_open` and `no_candidate`. The Helm Grafana overview charts them.
- **Transient failure (S5).** A 429/401/403 on a pin that has served the conversation:
  - cools that credential for 60 s;
  - serves the request from a fallback pin (`<key>#fallback`), so the detour stays on one spare;
  - leaves the original pin in place, so the conversation returns to its warm credential after the cooldown.

  Quota exhaustion and a pin created by the failing request itself still move the pin.
- **Atomic first pin (S6).** Pins are claimed with compare-and-set (`INSERT … ON CONFLICT DO UPDATE … WHERE account_id IN (expected, new) OR updated_at < stale_cutoff RETURNING`). A request that loses the race re-reads the winner and routes to it.
- **Purge (S11).** The sticky cleanup loop deletes expired `cliproxy_sticky_sessions` rows. It uses the same lifetime as the lookup.
- **Scoring (S4).** An unmeasured credential scores as half used, not fully used. A request whose model has no prefixed credential logs a throttled warning.

## Capabilities

### New capability: none (extends existing behavior)

## Impact

- Affected specs: `sticky-session-operations` (adds CLIProxyAPI credential-pin requirements).
- Affected backend code: `app/modules/proxy/cliproxy_account_routing.py`, `affinity.py`, `api.py`, `claude_sidecar_dispatch.py`, `responses_chat_bridge.py`, `responses_provider_dispatch.py`, `sticky_repository.py`, `app/modules/sticky_sessions/cleanup_scheduler.py`, `app/core/metrics/prometheus.py`.
- Helm Grafana overview dashboard gains one panel. No frontend changes, no migrations, no new settings.
- Rollout recommendation: enable CLIProxyAPI `routing.session-affinity: true` as defence in depth for requests that bypass the codex-lb router.
