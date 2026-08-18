## 1. Pricing registry

- [x] 1.1 Add canonical `claude-opus-5` and `claude-sonnet-5` `ModelPrice` rows (Opus 5 `$5/$0.50/$25`, Sonnet 5 `$2/$0.20/$10`)
- [x] 1.2 Add `*claude-opus-5*` and `*claude-sonnet-5*` aliases so `cc/` and `cp-` prefixes resolve

## 2. Historical backfill

- [x] 2.1 Add Alembic migration on `20260727_000000_merge_fork_and_upstream_1_22_heads` that recomputes NULL `claude_sidecar` `cost_usd` from the current pricing table
- [x] 2.2 Downgrade only Opus 5 / Sonnet 5 sidecar rows

## 3. Regression coverage

- [x] 3.1 Unit tests: canonical and `cc/`-prefixed Opus 5 / Sonnet 5 pricing lookup
- [x] 3.2 `add_log` persists non-NULL cost for `cc/claude-opus-5`
- [x] 3.3 Integration test: backfill fills Opus 5 / Sonnet 5 rows and leaves unknown models NULL

## 4. Verification

- [x] 4.1 `openspec validate price-claude-opus-5-sonnet-5 --strict`
- [ ] 4.2 `uv run pytest` for the focused pricing, request-log, and migration tests
