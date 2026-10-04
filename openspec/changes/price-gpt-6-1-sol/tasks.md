## 1. Pricing registry

- [x] 1.1 Add the `gpt-6.1-sol` `ModelPrice` row from the published list rates
- [x] 1.2 Resolve dated snapshots and `codex/` / `openai/` prefixes through a bounded identity checked before the GPT-6 matcher

## 2. Historical backfill

- [x] 2.1 Add Alembic revision `20261003_010000_backfill_gpt_6_1_sol_costs` on `20261003_000000_price_external_cache_reads` with frozen rates and id rule
- [x] 2.2 Skip settled provenance, already-priced rows, and lookalikes; apply lifetime deltas; patch buckets below the refold floor; arm `upgrade_repair_from`; leave `downgrade()` a no-op

## 3. Regression coverage

- [x] 3.1 Unit tests for canonical, dated, prefixed, and sidecar-prefixed pricing, tier and long-context math, and lookalikes
- [x] 3.2 Unit tests that a GPT-6.1 Sol grant admits supported ids, rejects lookalikes, and does not cross with GPT-6 Sol
- [x] 3.3 `add_log` persists static-table cost for `gpt-6.1-sol`
- [x] 3.4 Integration test: the backfill prices every tier and id form, leaves lookalikes and settled rows alone, moves the lifetime rollups, patches the unrefoldable bucket, arms the repair, and survives downgrade and rerun

## 4. Verification

- [x] 4.1 `openspec validate price-gpt-6-1-sol --strict`
- [x] 4.2 `uv run pytest` for the focused pricing, access, request-log, usage-summary, and migration tests
- [x] 4.3 Dry run the upgrade on a copy of the live database
