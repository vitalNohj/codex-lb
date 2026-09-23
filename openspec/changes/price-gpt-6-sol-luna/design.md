## Context

`calculated_cost_from_log` prices native Codex rows from `DEFAULT_PRICING_MODELS`. GPT-6 Astra already resolves, including dated snapshots and `codex/` / `openai/` prefixes. GPT-6 Sol and GPT-6 Luna do not, so `add_log` stores `cost_usd = NULL` and the dashboard shows a blank cost. External catalog lookup does not run on the native path.

## Goals / Non-Goals

**Goals:**

- Resolve `gpt-6-sol` and `gpt-6-luna` (including snapshot suffixes and `codex/` / `openai/` prefixes) to published OpenAI list prices
- Persist cost on new request logs through the existing `add_log` path
- Backfill historical NULL rows for those two ids, including folded usage-rollup deltas
- Keep a grant of the canonical id from admitting unrelated strings that only contain the name

**Non-Goals:**

- Teaching the external-price catalog to price native Codex models
- Cache-write or Batch-tier pricing (`ModelPrice` has no cache-write field)
- Changing sidecar routing, model allowlists, or the running process

## Decisions

- Add two canonical `ModelPrice` rows using OpenAI's published API rates (2026-09-22). Sol standard `$2 / $0.20 cache-hit / $10`. Luna standard `$0.10 / $0.01 / $0.50`. Fast/priority is 2x. Flex is 0.5x. Long context above 272,000 input tokens is 2x input and cache and 1.5x output. Same shape as GPT-6 Astra. Flex long-context keeps the existing flex-rate multiplier path and does not read the long-context fields.
- Extend the bounded versioned identity so `gpt-6-astra`, `gpt-6-sol`, and `gpt-6-luna` (optional `codex/` or `openai/` prefix, optional date suffix) canonicalize before legacy globs. `gpt-6-sol-pro` and `unrelated/gpt-6-sol` stay unrecognized.
- Do not add `*gpt-6-sol*` or `*gpt-6-luna*` globs. The versioned identity already accepts the canonical id, a dated snapshot, and a `codex/` or `openai/` prefix. A leading-star glob would also price `gpt-6-sol-pro`.
- Exempt `gpt-6-astra`, `gpt-6-sol`, and `gpt-6-luna` from access-identity collapse. Astra still has a leading-star glob. Sol and Luna do not, and the exemption keeps a later glob from widening their grants. Other pricing aliases stay collapsed: a grant of `gpt-5.4` must still admit `gpt-5.4-2026-03-17`.
- Copy the GPT-6 Astra backfill onto head `20260919_000000_add_openai_compat_endpoints`. The SQL prefilter is `lower(model)` against `%gpt-6-sol%` or `%gpt-6-luna%`, so PostgreSQL still selects uppercase ids. A row is priced only when `resolve_versioned_model_id` returns one of those two ids. Skip external provenance and already-priced rows, apply rollup deltas only for folded `max(id)` account groups, arm `upgrade_repair_from`, and leave `downgrade()` a no-op. Lock `account_usage_rollup_state` id 1 before reading `folded_through`, and hold that lock until the migration transaction commits, so a concurrent fold cannot advance the watermark over a still-NULL row. Do not edit the applied Astra migration.

## Risks / Trade-offs

- [Published rates can change] → Keep rates in the existing registry and pin them with lookup and `add_log` tests.
- [Backfill is estimated list-price, not an invoice] → Same as other native Codex costs. Subscription traffic still spends quota. The dollar figure is the published API list price.
- [A reversing downgrade would destroy costs the migration never wrote] → `downgrade()` is a no-op, same as the Astra backfill.
- [Costs stay blank until the process restarts and the migration runs] → The running service is left untouched. Restart is an operator step.

## Migration Plan

1. Deploy the price rows and the backfill revision.
2. Restart the service so new inserts use the rows and startup runs the migration.
3. Rollback is a code revert. Do not blank `cost_usd` that the migration or the request path already wrote.

## Open Questions

- none
