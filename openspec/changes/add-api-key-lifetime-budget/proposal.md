# Add a one-time (lifetime) API key budget

## Why

An owner gives a key to a friend with a fixed amount to spend: a total that never resets, not a daily or monthly allowance. Today every limit window rolls over, an unknown window silently becomes a 7-day reset, and two leaks let a shared key spend more than its budget measures: a model with no known price is charged $0, and a stream the client abandons before the final usage arrives is charged $0 too.

## What Changes

- **`lifetime` limit window.** A new `LimitWindow` value. Its `reset_at` stays `NOT NULL` and is pinned to a far-future sentinel (`9999-12-31`), so the reset sweep and the reservation compare-and-swap keep working unchanged. `limit_windows.py` returns no window length for it and raises `ValueError` for an unknown window instead of falling back to seven days.
- **Never resets.** The hourly sweep (`reset_expired_limits`) and the lazy admission reset skip lifetime limits whatever their stamp says. `Reset usage` keeps lifetime spend; raising the maximum is the top-up.
- **Backfill since creation.** A lifetime limit added to an existing key starts at the key's successful spend since the key was created (from request logs).
- **Exhaustion.** An exhausted lifetime budget answers `402 insufficient_quota` ("API key cost_usd lifetime budget exhausted. Raise the key's budget to continue."), with no reset time: it never resets, so a retry cannot help. Resetting limits keep their `429` (or the key's `rate_limit_as_payment_required` `402`) with "Usage resets at …".
- **Clients see no sentinel.** Dashboard, `/v1/usage` and `/api/codex/usage` report `reset_at: null` for a lifetime limit; Codex `/status` shows it as a windowless entry.
- **Unpriced models on shared cost budgets.** A key that is shared (`is_shared`) and has any `cost_usd` limit refuses a model with no known price, `403 model_not_priced`, before anything is reserved or sent upstream. Each dispatch path supplies the price check its own settlement uses: the static table (Codex, Ollama, OmniRoute, images, transcription), the persisted external price store under the route's pricing provider (CLIProxyAPI, OpenRouter, OrcaRouter, OpenCode Go, OpenAI-compatible endpoints), the model source's own rates, or "never charged" (model listings, file uploads). An alias pool needs every routable target priced. Unshared keys and shared keys without a cost limit keep serving every model.
- **Abandoned streams are charged.** A stream the client abandons after the upstream started streaming it is settled at its reservation (`charge_reserved_usage`) instead of released at $0, on the Codex HTTP and WebSocket paths and the CLIProxyAPI chat and native Responses paths. A stream abandoned before anything was relayed is still released.
- **Migration** `20261021_000000_add_lifetime_api_key_limit_window`: PostgreSQL `ALTER TYPE limit_window ADD VALUE IF NOT EXISTS 'lifetime'`; SQLite needs nothing. The downgrade is a no-op (an enum value cannot be dropped in place).
- **Dashboard.** A "One-time (never resets)" window option, the same label wherever a limit's window is shown, and a nullable `resetAt`. Strings in en, ko and zh-CN.

## Out of scope

- Full-estimate hard admission, an allow-final-request policy, mid-stream cutoff: the final in-flight request may overshoot the budget.
- Per-key Claude/xAI account scoping; reset-credit defaults; calendar windows; routing and sticky sessions.

## Impact

- Affected specs: `api-keys`.
- Backend: `app/db/models.py`, migration, `app/core/exceptions.py`, `app/core/usage/external_pricing/service.py`, `app/modules/api_keys/{limit_windows,repository,schemas,service}.py`, `app/modules/model_sources/catalog.py`, `app/modules/proxy/{api,api_key_pricing,schemas,claude_sidecar_dispatch,cliproxy_responses_dispatch}.py`, `app/modules/proxy/_service/{api_key_usage,streaming/retry,websocket/mixin}.py`, `app/modules/quota_planner/warmup.py`.
- Frontend: api-keys schemas, `limit-windows.ts` (new), limit rule card, key table, edit dialog, APIs key info, locales.
