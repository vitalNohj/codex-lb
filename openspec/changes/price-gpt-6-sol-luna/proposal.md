## Why

GPT-6 Sol and GPT-6 Luna request logs persist `cost_usd = NULL` because the static pricing table has no row for those ids. Catalog auto-pricing never covers native Codex traffic, so Request Logs stays blank even though both models already route natively and OpenAI has published list rates.

## What Changes

- Add canonical OpenAI list prices for `gpt-6-sol` and `gpt-6-luna` (standard, Fast/priority, Flex, long-context)
- Recognize dated snapshots and `codex/` / `openai/` ids through the bounded versioned identity, without a leading-star glob
- Keep those leading-star aliases from widening API-key model grants
- Backfill historical `gpt-6-sol` and `gpt-6-luna` rows whose `cost_usd` is still NULL

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `api-keys`: cost accounting MUST recognize GPT-6 Sol and GPT-6 Luna (including suffixed and prefixed ids) and backfill historical NULL costs for those models

## Impact

- Code: `app/core/usage/pricing.py`, `app/core/usage/model_ids.py`, `app/modules/proxy/request_policy.py`
- Tests: `tests/unit/test_pricing.py`, `tests/unit/test_versioned_model_ids.py`, `tests/unit/test_request_logs_repository.py`, `tests/integration/test_usage_summary.py`, `tests/integration/test_migrations.py`
- DB: new Alembic data backfill on current head; no schema shape change
- Specs: `openspec/specs/api-keys/spec.md` via this change's delta spec
- No API, routing, or frontend changes; the dashboard already renders `cost_usd` when present
