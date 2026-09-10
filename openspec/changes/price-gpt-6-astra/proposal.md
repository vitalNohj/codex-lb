## Why

GPT-6 Astra request logs persist `cost_usd = NULL` whenever the static pricing table does not recognize `gpt-6-astra`. Catalog auto-pricing never covers native Codex traffic, so Astra stays `--` on Request Logs after a restart that dropped an uncommitted price row. Published OpenAI rates exist and already match the ~6k Astra rows priced before that restart (`$10 / $1 cache-hit / $50` per 1M).

## What Changes

- Add canonical OpenAI list prices for `gpt-6-astra` (standard, Fast/priority, Flex, long-context)
- Add a prefix-tolerant alias so snapshot and `codex/` / `openai/` ids resolve
- Backfill historical `gpt-6-astra` rows whose `cost_usd` is still NULL
- Add regression coverage at pricing lookup, `add_log`, and the backfill migration

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `api-keys`: cost accounting MUST recognize GPT-6 Astra (including suffixed and prefixed ids) and backfill historical NULL costs for those models

## Impact

- Code: `app/core/usage/pricing.py`
- Tests: `tests/unit/test_pricing.py`, `tests/unit/test_request_logs_repository.py`, `tests/integration/test_migrations.py`
- DB: new Alembic data backfill on current head; no schema shape change
- Specs: `openspec/specs/api-keys/spec.md` via this change's delta spec
- No API, routing, or frontend changes; the dashboard already renders `cost_usd` when present
