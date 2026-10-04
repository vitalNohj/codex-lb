## Why

GPT-6.1 Sol request logs persist `cost_usd = NULL` because the static pricing table has no row for `gpt-6.1-sol`, and the GPT-6 matcher does not recognize the dotted id. Its native Codex traffic has been logged with no dollar cost since it launched, so Request Logs and every cost total leave it out. OpenAI publishes list rates for it, and they differ from GPT-6 Sol's: the cache-read rate is half.

## What Changes

- Add the published list prices for `gpt-6.1-sol` (Standard, Fast/priority, Flex, long context)
- Recognize dated snapshots and `codex/` / `openai/` ids through a bounded identity of its own, checked before the GPT-6 matcher, so `gpt-6.1-sol` never resolves as `gpt-6-sol`
- Backfill historical `gpt-6.1-sol` rows whose `cost_usd` is still NULL, and move every usage rollup that already folded them

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `api-keys`: cost accounting MUST price GPT-6.1 Sol (including dated and prefixed ids), keep its grants bounded, and backfill historical NULL costs into request logs and the rollups that folded them

## Impact

- Code: `app/core/usage/pricing.py`, `app/core/usage/model_ids.py`
- Tests: `tests/unit/test_pricing.py`, `tests/unit/test_versioned_model_ids.py`, `tests/unit/test_request_logs_repository.py`, `tests/integration/test_usage_summary.py`, `tests/integration/test_migrations.py`
- DB: new Alembic data backfill `20261003_010000_backfill_gpt_6_1_sol_costs` on `20261003_000000_price_external_cache_reads`; no schema change
- Specs: `openspec/specs/api-keys/spec.md` via this change's delta spec
- No API, routing, or frontend changes. The dashboard already renders `cost_usd` when present.
