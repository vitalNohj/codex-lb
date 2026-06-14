# Sidecar Cost Capture — Context

## Background

The codex-lb dashboard shows per-request cost in the Request Logs table and aggregates cost in the Reports tab (daily totals, by-model, by-account). Cost is stored in the `request_logs.cost_usd` column.

### How cost worked before this change

At request-log insert time, `RequestLogsRepository.add_log()` hardcoded `cost_usd=None` on the `RequestLog` object, then immediately overwrote it with `calculated_cost_from_log()`, which:
1. Extracts token counts from the log row
2. Looks up the model in `DEFAULT_PRICING_MODELS` (exact match) or `DEFAULT_MODEL_ALIASES` (glob match)
3. Computes cost as `(billable_input/1M * input_rate) + (cached/1M * cached_rate) + (output/1M * output_rate)`
4. Applies service-tier multipliers

This approach has two fundamental gaps for sidecar traffic:

#### OpenRouter
- OpenRouter's API **already returns** `usage.cost` (in credits) in every response — authoritative, tokenizer-aware, up-to-date.
- The local pricing table had only 2 OpenRouter entries (`deepseek/deepseek-chat`, `google/gemini-2.5-pro-preview`).
- `extract_usage()` (shared by all three sidecars) reads `prompt_tokens`/`completion_tokens` but **drops `usage.cost` entirely**.
- Result: 95%+ of OpenRouter requests showed `$0.00`.

#### OmniRoute
- OmniRoute does **not** return a per-response cost; it computes cost internally from its own pricing config.
- The local pricing table had **zero** OmniRoute entries.
- Result: 100% of OmniRoute requests showed `$0.00`.

#### Historical rows
The Claude sidecar had the same problem and was fixed via an archived change (`fix-claude-sidecar-usage-and-cost` / migration `20260611_020000_backfill_claude_sidecar_request_log_costs`). That migration recomputed cost for historical `claude_sidecar` rows using the pricing table.

## Design Decisions

### Authoritative cost for OpenRouter, pricing table for OmniRoute
OpenRouter's `usage.cost` is captured and persisted directly. This is the "source of truth" — it uses the model's native tokenizer, includes any cached-token discounts, and is always current.

OmniRoute has no per-response cost. The only option is the pricing-table fallback. We added common OmniRoute model entries so the fallback produces non-zero values for popular models.

### `add_log(cost_usd=...)` signature
We added an optional `cost_usd` parameter to `add_log()`. When provided (not `None`), it is persisted directly and the pricing table is **not** consulted. This ensures:
- Authoritative OpenRouter cost is never overwritten by a stale local table
- The pricing table remains the fallback for all other cases (OmniRoute, direct traffic, etc.)

### Backfill uses pricing table for both
We cannot retroactively fetch OpenRouter's authoritative per-row cost (the generation ID is not stored). The backfill migration recomputes cost from token counts × pricing table for both sources, matching the Claude sidecar precedent.

### No frontend changes
The frontend already reads `costUsd` from the API and renders it via `formatCurrency()`. Once the backend stores a value, it appears automatically.

## Files Changed

### Core logic
- `app/modules/proxy/claude_sidecar_dispatch.py`: `SidecarUsage` + `cost_usd` field; `extract_usage()` reads `usage.cost`
- `app/modules/request_logs/repository.py`: `add_log(cost_usd=...)` parameter; conditional pricing-table fallback
- `app/modules/proxy/openrouter_sidecar_dispatch.py`: `_log_openrouter_request()` passes `usage.cost_usd`
- `app/modules/proxy/omniroute_sidecar_dispatch.py`: `_log_omniroute_request()` passes `usage.cost_usd` (will be `None`)
- `app/core/usage/pricing.py`: ~20 new pricing entries + aliases for OpenRouter & OmniRoute models

### Migration
- `app/db/alembic/versions/20260614_000000_backfill_openrouter_omniroute_request_log_costs.py`

### OpenSpec
- `openspec/changes/sidecar-cost-capture/proposal.md`
- `openspec/changes/sidecar-cost-capture/tasks.md`
- `openspec/changes/sidecar-cost-capture/spec.md`
- `openspec/changes/sidecar-cost-capture/context.md` (this file)

## Verification Strategy

1. **Unit tests**: `extract_usage` parses `usage.cost`; `add_log` persists passed cost vs falls back.
2. **Integration**: Run pytest on `app/modules/proxy`, `app/modules/request_logs`, `app/core/usage`.
3. **OpenSpec**: `openspec validate sidecar-cost-capture --strict` passes.
4. **Migration**: `uv run codex-lb-db upgrade` applies cleanly on a DB copy; single head maintained.
5. **End-to-end**: Restart service, send real OpenRouter request, confirm non-zero cost in Request Logs and Reports.