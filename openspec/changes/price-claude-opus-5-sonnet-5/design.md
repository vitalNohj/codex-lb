## Context

`calculated_cost_from_log` prices Claude sidecar rows from `DEFAULT_PRICING_MODELS` via longest-match aliases. Fable 5 and Opus 4.x already resolve. Opus 5 and Sonnet 5 do not, so `add_log` stores `cost_usd = NULL` and the dashboard shows `--`. Live store: ~16k `cc/claude-opus-5` rows in 7 days, all NULL cost, almost all with token usage. Claude OAuth never returns a dollar `usage.cost`, so the pricing table is the only source.

## Goals / Non-Goals

**Goals:**

- Resolve `claude-opus-5` and `claude-sonnet-5` (including `cc/` / `cp-` prefixes and date suffixes) to published Anthropic list prices
- Persist cost on new request logs through the existing `add_log` path
- Backfill historical NULL `claude_sidecar` rows that now resolve

**Non-Goals:**

- Client-specific cost paths (Cursor vs Kodus vs others)
- Changing routing, max-tokens floors, or CLIProxyAPI usage capture
- Authoritative per-request dollar amounts from Anthropic (OAuth does not expose them)
- Cache-write or Batch-tier pricing

## Decisions

- Add two canonical `ModelPrice` rows using Anthropic's published API rates: Opus 5 `$5 / $0.50 cache-hit / $25` and Sonnet 5 `$2 / $0.20 / $10` (USD per 1M tokens). Same shape as the existing Opus 4.8 / Fable 5 entries.
- Add `*claude-opus-5*` and `*claude-sonnet-5*` aliases so sidecar-prefixed ids match the way `*claude-fable-5*` already matches `cc/claude-fable-5`. Longest-match already prevents `*claude-opus-4*` from colliding.
- Reuse the 20260611 Claude sidecar cost backfill: scan `source = claude_sidecar AND cost_usd IS NULL`, recompute from the current table, skip models that still do not resolve. Downgrade NULLs only Opus 5 / Sonnet 5 sidecar rows so earlier Claude costs stay put.
- After rewriting costs, add the newly computed Opus 5 / Sonnet 5 `cost_usd` onto existing `account_usage_rollups` / `api_key_usage_rollups` rows for folded logs this migration actually repriced (`requested_at <= folded_through`). Leave `folded_through` unchanged. Rows that already had a price (inserted after the pricing deploy) must not be added again. Rewinding the watermark cannot rebuild request logs retention already deleted; those NULL-cost models folded as $0 so a cost-only delta is safe. Downgrade subtracts currently folded Opus 5 / Sonnet 5 dollars while costs are still present, then NULLs the request-log rows.
- Parent the migration on `20260727_000000_merge_fork_and_upstream_1_22_heads` (current single head).

## Risks / Trade-offs

- [Published rates can change] → Keep rates in the existing registry and pin them with lookup + `add_log` tests.
- [Sonnet 5 intro vs standard] → Anthropic made the `$2/$10` intro rate permanent on 2026-08-10; store that, not the retired `$3/$15`.
- [Backfill is estimated list-price, not invoice] → Same as every other Claude sidecar cost; OAuth is flat-rate. Dashboard already labels this as estimated cost.

## Migration Plan

1. Deploy code with the new prices (new requests get cost immediately after restart).
2. Run Alembic upgrade so historical NULL rows fill in.
3. Rollback: downgrade the backfill (Opus 5 / Sonnet 5 costs return to NULL) and revert the pricing rows.
