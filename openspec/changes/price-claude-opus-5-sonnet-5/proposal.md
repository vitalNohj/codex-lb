## Why

Claude sidecar request logs for `cc/claude-opus-5` (and `cc/claude-sonnet-5`) persist `cost_usd = NULL`, so Request Logs shows `--` even when token usage is present. Cursor looks fine only because recent Cursor traffic uses `cc/claude-fable-5`, which already has a pricing entry. The gap is the missing Opus 5 / Sonnet 5 rows in `DEFAULT_PRICING_MODELS`, not the client.

## What Changes

- Add canonical Anthropic list prices for `claude-opus-5` and `claude-sonnet-5`
- Add prefix-tolerant aliases so `cc/claude-opus-5`, `cp-claude-opus-5`, and date-suffixed ids resolve
- Backfill historical `claude_sidecar` rows whose `cost_usd` is still NULL now that those models resolve
- Add regression coverage at pricing lookup, `add_log`, and the backfill migration

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `api-keys`: cost accounting MUST recognize Claude Opus 5 and Sonnet 5 (including sidecar-prefixed ids) and backfill historical NULL sidecar costs for those models

## Impact

- Code: `app/core/usage/pricing.py`
- Tests: `tests/unit/test_pricing.py`, `tests/unit/test_request_logs_repository.py`, `tests/integration/test_migrations.py`
- DB: new Alembic data backfill on current head; no schema shape change
- Specs: `openspec/specs/api-keys/spec.md` via this change's delta spec
- No API, routing, or frontend changes; the dashboard already renders `cost_usd` when present
