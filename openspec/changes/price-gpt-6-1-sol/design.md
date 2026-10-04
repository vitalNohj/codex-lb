## Context

`calculated_cost_from_log` prices native Codex rows from `DEFAULT_PRICING_MODELS`. `gpt-6.1-sol` has no entry there, and `_GPT6_NATIVE_ID` (`gpt-6-(astra|sol|luna)`) does not match the dotted id, so `add_log` stores `cost_usd = NULL` and the dashboard shows a blank cost. External catalog lookup does not run on the native path.

## Goals / Non-Goals

**Goals:**

- Resolve `gpt-6.1-sol` (dated snapshots, `codex/` and `openai/` prefixes, any letter case, one leading `cc/`, `cp-`, or `cp_`) to OpenAI's published list prices
- Persist cost on new request logs through the existing `add_log` path
- Backfill historical NULL rows and move every rollup that folded them by exactly the backfilled cost
- Keep `gpt-6-sol` and `gpt-6.1-sol` distinct for pricing and for grants

**Non-Goals:**

- Cache-write or Batch pricing (`ModelPrice` has no cache-write field)
- Fast-tier long-context pricing. The priority branch of `_effective_rates` returns the Fast rates without a long-context step for every model today.
- Pricing rows retention already pruned. Their buckets keep only token sums, not the per-request tier and context size a price needs.
- Changing sidecar routing, model allowlists, or the running process

## Decisions

- Add one `ModelPrice` row at OpenAI's published rates (fetched 2026-10-03): standard `2 / 0.10 / 10`, Fast `4 / 0.20 / 20`, Flex `1 / 0.05 / 5`, long context above 272,000 input tokens `4 / 0.20 / 15`. It has the same shape as GPT-6 Sol with half the cached-input rate.
- Add a separate bounded regex `_GPT61_SOL_ID` and check it before `_GPT6_NATIVE_ID` in `resolve_versioned_model_id`. The dot keeps the older matcher from reading 6.1 as a suffixed 6 Sol id. Do not add a leading-star glob: `gpt-6.1-sol-pro`, `gpt-6.1-sol-high`, and `unrelated/gpt-6.1-sol` stay unpriced. Access identity already runs the versioned matcher first, so `_BOUNDED_NATIVE_PRICE_KEYS` needs no entry.
- The backfill follows `20260922_000000_backfill_gpt_6_sol_luna_costs`: lock the fold-state row, prefilter on `lower(model)`, price only NULL-cost rows with no settled provenance, apply lifetime deltas through the duplicate-group `max(id)` rule, arm `upgrade_repair_from`, and make `downgrade()` a no-op. It differs in two ways:
  - The rates and the id rule are frozen in the revision file. A merged migration must keep writing the same values after the live table changes. An earlier backfill test broke when the live table moved under it.
  - A row below the first hour the post-upgrade repair can refold adds its cost to its hourly bucket (`cost_usd` and `cost_count`) and demand slot directly, as `20261003_000000_price_external_cache_reads` does. Retention already pruned part of that hour, so the repair never refolds it.
- The frozen id rule is the bounded regex, or the exact key behind one leading `cc/`, `cp-`, or `cp_`. That is what `get_pricing_for_model` resolves to this entry. The two agreed on 1,512 id variants covering case, surrounding whitespace, prefixes, and lookalikes.

## Risks / Trade-offs

- [Published rates can change] → Tests pin the live row. The migration keeps its own copy, the price in effect when the traffic happened.
- [The backfill is a list price, not an invoice] → Same as other native Codex costs. Subscription traffic still spends plan quota.
- [Pruned rows stay unpriced] → An hour below the refold floor gains only its surviving rows' cost.
- [Cost limits are not raised] → `api_key_limits.current_value` of a `cost_usd` limit restarts at each window reset. Raising it now could block a key for usage it was already allowed.
- [A reversing downgrade would destroy costs it never wrote] → `downgrade()` is a no-op, same as the Sol and Luna backfill.

## Migration Plan

1. Deploy the price row and the backfill revision.
2. Restart. Startup runs the migration, and new inserts use the row.
3. The post-upgrade repair refolds hourly and demand buckets from the armed marker.
4. Rollback is a code revert. Do not blank `cost_usd` that the migration or the request path wrote.

## Open Questions

- none
