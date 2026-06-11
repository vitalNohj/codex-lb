# Fix Claude Sidecar Usage Display and Add Claude Cost Reporting

## Why

Two regressions/gaps around the Claude sidecar surfaced on the dashboard:

1. **Session usage flapping.** The quota poller fetches Claude OAuth usage
   (`five_hour` / `seven_day` buckets) on every 60s poll and replaces the
   snapshot wholesale. Anthropic's `/api/oauth/usage` endpoint intermittently
   returns HTTP 429; when that happens the poller persists
   `oauth_usage = null`, and the dashboard's 5h/weekly bars flip to
   "Unavailable" until the next successful poll. Observed live: alternating
   `present` / `NULL` snapshots every other poll.

2. **Reports show $0 for sidecar traffic.** `DEFAULT_PRICING_MODELS` contains
   no Claude entries, and sidecar request logs store the dashboard-facing
   prefixed model id (e.g. `cp-claude-fable-5`). `calculated_cost_from_log`
   therefore resolves no price and `cost_usd` stays `NULL`, so the Reports
   page shows no dollar amount for Claude usage.

## What Changes

- Quota poller carries forward the last-known per-auth OAuth usage from the
  previous snapshot when a fresh fetch fails (e.g. 429/timeout), instead of
  clearing it. Fresh successful fetches still replace the data.
- Add Claude model pricing (Anthropic list prices, June 2026) and alias
  patterns to `DEFAULT_PRICING_MODELS` / `DEFAULT_MODEL_ALIASES`, with
  prefix-tolerant patterns so configured sidecar prefixes (`cp-`, etc.)
  resolve to the canonical Claude price.
- Backfill `cost_usd` for historical `claude_sidecar` request logs via an
  Alembic migration so the Reports page reflects past usage.

## Impact

- Affected specs: `dashboard-sidecar-management` (OAuth usage retention),
  `reports` (Claude cost coverage).
- Affected code: `app/modules/claude_sidecar/quota_poller.py`,
  `app/core/usage/pricing.py`, new Alembic migration.
- No API or schema shape changes; `cost_usd` values become non-null for
  Claude models.
