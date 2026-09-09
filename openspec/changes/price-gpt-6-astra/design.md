## Context

`calculated_cost_from_log` prices native Codex rows from `DEFAULT_PRICING_MODELS`. GPT-5.6 personalities already resolve. GPT-6 Astra does not, so `add_log` stores `cost_usd = NULL` and the dashboard shows `--`. External catalog lookup does not run on the native path, so a missing static-table row is permanent until someone adds it.

## Goals / Non-Goals

**Goals:**

- Resolve `gpt-6-astra` (including snapshot suffixes and `codex/` / `openai/` prefixes) to published OpenAI list prices
- Persist cost on new request logs through the existing `add_log` path
- Backfill historical NULL `gpt-6-astra` rows that now resolve, including folded usage-rollup deltas

**Non-Goals:**

- Teaching the external-price catalog to price native Codex models
- Cache-write or Batch-tier pricing
- Restarting or hot-patching a running process

## Decisions

- Add one canonical `ModelPrice` row using OpenAI's published API rates: standard `$10 / $1 cache-hit / $50`, Fast/priority 2x, Flex 0.5x, long-context (>272K input) `$20 / $2 / $75`. Same shape as GPT-5.6 Sol.
- Add `*gpt-6-astra*` so `gpt-6-astra-2026-09-03`, `codex/gpt-6-astra`, and `openai/gpt-6-astra` resolve. Do not alias bare `gpt-6`.
- Scan `model LIKE '%gpt-6-astra%' AND cost_usd IS NULL`, recompute from the current table, skip rows that still do not resolve. Set `cost_source = static_table` on filled rows.
- Skip rows whose writer already owns the price: any `price_status`, or a `cost_source` other than `static_table`. On those rows a NULL cost is the external resolver's answer, not a gap, and the static table's substring aliases must not answer for an id they have never heard of. Same rule as read-side `declares_price_provenance`.
- After rewriting costs, add the newly computed `cost_usd` onto existing `account_usage_rollups` / `api_key_usage_rollups` rows for folded logs this migration actually repriced (`requested_at <= folded_through`). Leave `folded_through` unchanged.
- Credit the account rollup only for a repriced row that is the true `max(id)` of its `(account_id, request_id, requested_at)` group, resolved over all rows rather than the repriced subset, because `deduped_usage_aggregate_stmt` folds exactly that row. The per-API-key aggregate does not deduplicate, so every repriced row counts there.
- Arm the existing `account_usage_rollup_state.upgrade_repair_from` marker at the earliest repriced hour. The hourly and demand folds sum `cost_usd`, so buckets below `hourly_folded_through` are stale until the next fold pass refolds that range from raw. The conversation satellite stores only `request_count` and needs no repair.
- Parent the migration on `20260903_000000_merge_fork_and_upstream_1_24_heads` (current single head).

## Risks / Trade-offs

- [Published rates can change] → Keep rates in the existing registry and pin them with lookup + `add_log` tests.
- [Backfill is estimated list-price, not invoice] → Same as GPT-5.6 native cost; dashboard already labels this as estimated cost.
- [A reversing downgrade would destroy costs the migration never wrote] → `downgrade()` is a deliberate no-op. Nothing records which rows the migration filled: a row it repriced and a row the request path priced from the same static table end up identical (`cost_usd` set, `cost_source='static_table'`), so any reversal keyed on the model or on `cost_source` blanks legitimate prices and desynchronizes the rollups that contain them. Leaving correct list prices in place is the safe direction, and re-running `upgrade()` is a no-op because those rows are no longer NULL. Same choice as `20260722_000000_backfill_request_log_useragent_families`.

## Migration Plan

1. Deploy code with the new prices (new requests get cost immediately after restart).
2. Run Alembic upgrade so historical NULL rows fill in.
3. The next hourly fold pass consumes the armed `upgrade_repair_from` marker and refolds the repriced range, so hourly and demand dollar reports pick up the backfilled cost.
4. Rollback: downgrade is a no-op for data; reverting the pricing row stops new requests from resolving Astra prices. Already-computed costs are retained deliberately.
