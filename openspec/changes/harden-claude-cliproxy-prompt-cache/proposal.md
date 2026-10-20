# Harden Claude prompt caching through CLIProxyAPI

## Why

Claude runs through CLIProxyAPI's OpenAI-compatible chat route. The CLIProxyAPI verification scout (`clb-oa-19`) ran a 6-turn tool session against CLIProxyAPI v8 and Anthropic. It confirmed that prompt caching and sticky credentials work on that route, and found four gaps:

- CLIProxyAPI reports Claude cache-creation tokens in `prompt_tokens_details.cache_write_tokens` (and `cached_creation_tokens`). codex-lb dropped them and billed them as plain input. Anthropic bills a 1-hour cache write at 2× the input rate, and CLIProxyAPI moves Claude Code OAuth requests to the 1-hour cache.
- When the credential router could not name a prefixed credential, a Claude request went out with the plain model name. CLIProxyAPI then round-robins it across accounts, and each account has its own cold cache.
- Nothing pinned the chat body that codex-lb sends. A reordered tool list, a moved `reasoning_effort`, or a rewritten history message invalidates Anthropic's prefix cache without anyone noticing.
- CLIProxyAPI's Claude Code OAuth requests carry a per-request hash in the first system block. Only `api.anthropic.com` strips that block before it looks up the cache. Any hop that rewrites the body makes every turn a full write, and nothing showed when that happened.

## What Changes

- **Cache-write accounting.** The sidecar usage parser reads cache writes from streamed and non-streamed chat usage. Request logs store them in a new `cache_write_input_tokens` column, and pricing bills them at 2× the input rate. Cache reads keep the read rate, and the rest of the prompt keeps the input rate. The dashboard request details show a cache-write segment.
- **No untagged Claude requests.** `apply_cliproxy_account_route` raises `CliproxyClaudeRouteRefused` for a Claude model when it cannot name a prefixed credential, because capacity routing is off, no prefixed credential serves the model, or selection failed. The Claude chat dispatch answers `503 cliproxy_claude_route_unavailable`, releases the reservation, logs the request, and sends nothing. Poller holds still answer first: a far hold stays a `429`, and a near hold is waited out before the route is tried again. When every Claude auth is disabled, the existing no-enabled-account `503` is kept. Other CLIProxyAPI families keep their plain-name fallback.
- **Byte-stable chat body.** The operator reasoning-effort override now always places `reasoning_effort` at the end of the body, whether or not the client sent an effort. Tests build every turn of a Responses tool session through the real translation and payload steps, and assert that each turn's wire bytes repeat the previous turn and only append messages. Those steps are the same with and without the effort override, with per-turn client metadata, and with a derived `prompt_cache_key`. An integration test checks that the bodies CLIProxyAPI receives behave the same way, on one credential.
- **Direct-to-Anthropic signal.** `codex_lb_cliproxy_claude_sticky_cache_total{result}` counts the Claude turns served on their conversation's existing pin with a prompt of at least 4,096 tokens, split by whether they read the cache. A miss logs `cliproxy_claude_sticky_cache_miss`, at most once every ten minutes per credential. The Helm chart adds a `CodexLBClaudeStickyCacheMiss` warning. The README, troubleshooting, and model-pricing docs state that CLIProxyAPI must reach `api.anthropic.com` directly.

## Out of scope

- Route changes, a native Messages path, xAI.
- A CLIProxyAPI `routing.session-affinity` check. The sibling xAI pass-through change owns that guard.

## Capabilities

### New capability: none (extends existing behavior)

## Impact

- Affected specs: `external-model-pricing`, `sticky-session-operations`, `proxy-runtime-observability`.
- Backend: `app/core/usage/pricing.py`, `app/core/usage/logs.py`, `app/core/usage/external_pricing/service.py`, `app/db/models.py`, migration `20261019_000000_add_request_log_cache_write_tokens`, `app/modules/request_logs/*`, `app/modules/proxy/claude_sidecar_dispatch.py`, `app/modules/proxy/cliproxy_account_routing.py`, `app/modules/proxy/sidecar_model_profiles.py`, `app/core/metrics/prometheus.py`.
- Frontend: the request-details cost breakdown gains a cache-write segment.
- Helm: one new PrometheusRule alert.
- Operators: a Claude request that previously went out with the plain model name, because no prefixed CLIProxyAPI credential was available, now receives a `503`.
