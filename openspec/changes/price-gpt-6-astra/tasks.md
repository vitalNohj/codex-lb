## 1. Pricing registry

- [x] 1.1 Add canonical `gpt-6-astra` `ModelPrice` row (`$10/$1/$50` standard, Fast 2x, Flex 0.5x, long-context `$20/$2/$75`)
- [x] 1.2 Add `*gpt-6-astra*` alias so snapshot and `codex/` / `openai/` prefixes resolve

## 2. Historical backfill

- [x] 2.1 Add Alembic migration on `20260903_000000_merge_fork_and_upstream_1_24_heads` that recomputes NULL `gpt-6-astra` `cost_usd` from the current pricing table
- [x] 2.2 Skip rows that declare external price provenance (`price_status` set, or `cost_source` other than `static_table`)
- [x] 2.3 Add folded GPT-6 Astra cost deltas onto existing usage-rollup rows without changing `folded_through`
- [x] 2.4 Credit the account rollup only for repriced rows that are their duplicate group's true `max(id)`
- [x] 2.5 Arm `upgrade_repair_from` at the earliest repriced hour so hourly/demand cost buckets refold
- [x] 2.7 Make a running replica consume that marker: `run_hourly_fold_pass` re-checks it every pass instead of only at process start
- [x] 2.8 Keep one state contract in the repair owner: marker-driven passes are `marker_only` and never write the process-start latch, so neither a racing marker clear nor a chunk-bounded incomplete repair can re-arm the trailing-window refold
- [x] 2.6 Make `downgrade()` a no-op: the repriced set is not recorded, so any reversal would blank costs the migration never wrote

## 3. Regression coverage

- [x] 3.1 Unit tests: canonical, snapshot, and prefixed GPT-6 Astra pricing lookup plus tier/long-context math
- [x] 3.2 `add_log` persists non-NULL static-table cost for `gpt-6-astra`
- [x] 3.3 Integration test: backfill fills GPT-6 Astra rows and leaves unknown models NULL
- [x] 3.4 Integration test: external price provenance and pre-existing prices survive the backfill
- [x] 3.5 Integration test: duplicate request rows do not double-count in the account rollup
- [x] 3.6 Integration test: the hourly repair marker is armed without moving any fold watermark
- [x] 3.7 Integration test: repeat upgrade is idempotent and rollback is non-destructive
- [x] 3.8 Integration test: an armed marker is consumed by an already-latched process, and a marker cleared between the unlocked probe and the locked read refolds nothing
- [x] 3.9 Integration test: an incomplete marker repair leaves the process-start latch set and still converges from the persisted marker across passes

## 4. Verification

- [x] 4.1 `openspec validate price-gpt-6-astra --strict`
- [x] 4.2 `uv run pytest` for the focused pricing, request-log, and migration tests
