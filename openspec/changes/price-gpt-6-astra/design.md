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
- After rewriting costs, add the newly computed `cost_usd` onto existing `account_usage_rollups` / `api_key_usage_rollups` rows for folded logs this migration actually repriced (`requested_at <= folded_through`). Leave `folded_through` unchanged.
- Parent the migration on `20260903_000000_merge_fork_and_upstream_1_24_heads` (current single head).

## Risks / Trade-offs

- [Published rates can change] → Keep rates in the existing registry and pin them with lookup + `add_log` tests.
- [Backfill is estimated list-price, not invoice] → Same as GPT-5.6 native cost; dashboard already labels this as estimated cost.
- [Downgrade NULLs every Astra cost, including rows priced at insert time] → Same rollback shape as the Opus 5 backfill; production does not downgrade.

## Migration Plan

1. Deploy code with the new prices (new requests get cost immediately after restart).
2. Run Alembic upgrade so historical NULL rows fill in.
3. Rollback: downgrade the backfill (Astra costs return to NULL) and revert the pricing row.
