## 1. Pricing registry

- [x] 1.1 Add canonical `gpt-6-sol` and `gpt-6-luna` `ModelPrice` rows from the published list rates
- [x] 1.2 Resolve dated snapshots and `codex/` / `openai/` prefixes through the bounded versioned identity, without a leading-star glob
- [x] 1.3 Extend the bounded versioned identity and keep those leading-star aliases from widening API-key grants

## 2. Historical backfill

- [x] 2.1 Add an Alembic migration on `20260919_000000_add_openai_compat_endpoints` that recomputes NULL `gpt-6-sol` and `gpt-6-luna` `cost_usd`
- [x] 2.2 Skip external price provenance, skip already-priced rows, apply folded rollup deltas, arm `upgrade_repair_from`, and leave `downgrade()` a no-op

## 3. Regression coverage

- [x] 3.1 Unit tests for canonical, snapshot, and prefixed pricing plus tier and long-context math
- [x] 3.2 Unit tests that a Sol or Luna grant admits supported ids and rejects lookalikes
- [x] 3.3 `add_log` persists static-table cost for `gpt-6-sol` and `gpt-6-luna`
- [x] 3.4 Integration test: backfill fills both models, leaves unknown and externally owned rows alone, and repairs folded rollups

## 4. Verification

- [x] 4.1 `openspec validate price-gpt-6-sol-luna --strict`
- [x] 4.2 `uv run pytest` for the focused pricing, access, request-log, and migration tests
