# Tasks: OpenRouter & OmniRoute Request Cost Capture

## Phase 1: Capture cost in shared usage extractor
- [x] Add `cost_usd: float | None = None` to `SidecarUsage` dataclass in `app/modules/proxy/claude_sidecar_dispatch.py`
- [x] Add `_float_field()` helper mirroring `_int_field()`
- [x] In `extract_usage()`, read `usage.cost` and populate `SidecarUsage.cost_usd`

## Phase 2: Let add_log accept authoritative cost
- [x] Add `cost_usd: float | None = None` parameter to `add_log()` in `app/modules/request_logs/repository.py`
- [x] Persist passed `cost_usd` on `RequestLog` creation
- [x] Only run pricing-table fallback when passed `cost_usd is None`

## Phase 3: Wire OpenRouter dispatch
- [x] Pass `cost_usd=usage.cost_usd if usage else None` in `_log_openrouter_request()` call to `repo.add_log()`

## Phase 4: Wire OmniRoute dispatch & add pricing entries
- [x] Pass `cost_usd=usage.cost_usd if usage else None` in `_log_omniroute_request()` call to `repo.add_log()`
- [x] Add common OpenRouter model pricing entries to `DEFAULT_PRICING_MODELS` in `app/core/usage/pricing.py`
- [x] Add OmniRoute model pricing entries to `DEFAULT_PRICING_MODELS`
- [x] Add matching aliases to `DEFAULT_MODEL_ALIASES` for both providers

## Phase 5: Backfill historical rows
- [x] Create Alembic migration `20260614_000000_backfill_openrouter_omniroute_request_log_costs.py` revising the current head
- [x] Migration targets rows where `source IN ('openrouter_sidecar','omniroute_sidecar')` and `cost_usd IS NULL OR cost_usd == 0`
- [x] Recomputes cost using pricing table (authoritative OpenRouter per-row cost not retroactively available)
- [x] Provides `downgrade()` that sets `cost_usd = NULL` for affected rows

## Phase 6: OpenSpec change folder
- [x] `proposal.md` - problem/solution/impact
- [x] `tasks.md` - this file
- [x] `spec.md` - normative delta spec
- [x] `context.md` - narrative context
- [x] Run `openspec validate sidecar-cost-capture --strict`

## Verification
- [x] Run relevant pytest suites covering proxy, request logs, pricing, OpenRouter, and OmniRoute - all pass
- [x] Add/adjust tests for:
  - `extract_usage` parses `usage.cost`
  - `add_log` persists passed cost and falls back when omitted
  - OpenRouter dispatch persists authoritative cost (including stream paths)
- [x] Run `openspec validate --specs` and `openspec validate sidecar-cost-capture --strict`
- [x] Run `uv run codex-lb-db upgrade head` and `uv run codex-lb-db check`; confirm single head and no schema drift
- [ ] Restart service (`systemctl --user restart codex-lb.service`), send real OpenRouter request, confirm non-zero cost in Request Logs and Reports tab