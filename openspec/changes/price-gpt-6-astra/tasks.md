## 1. Pricing registry

- [x] 1.1 Add canonical `gpt-6-astra` `ModelPrice` row (`$10/$1/$50` standard, Fast 2x, Flex 0.5x, long-context `$20/$2/$75`)
- [x] 1.2 Add `*gpt-6-astra*` alias so snapshot and `codex/` / `openai/` prefixes resolve

## 2. Historical backfill

- [x] 2.1 Add Alembic migration on `20260903_000000_merge_fork_and_upstream_1_24_heads` that recomputes NULL `gpt-6-astra` `cost_usd` from the current pricing table
- [x] 2.2 Downgrade only GPT-6 Astra rows
- [x] 2.3 Add folded GPT-6 Astra cost deltas onto existing usage-rollup rows without changing `folded_through`

## 3. Regression coverage

- [x] 3.1 Unit tests: canonical, snapshot, and prefixed GPT-6 Astra pricing lookup plus tier/long-context math
- [x] 3.2 `add_log` persists non-NULL static-table cost for `gpt-6-astra`
- [x] 3.3 Integration test: backfill fills GPT-6 Astra rows and leaves unknown models NULL

## 4. Verification

- [x] 4.1 `openspec validate price-gpt-6-astra --strict`
- [x] 4.2 `uv run pytest` for the focused pricing, request-log, and migration tests
