# Proposal: OpenRouter & OmniRoute Request Cost Capture

## Problem

OpenRouter and OmniRoute sidecar requests show `$0.00` cost in the Reports tab and Request Logs because:

1. **OpenRouter** returns an authoritative `usage.cost` field in every API response, but `extract_usage()` drops it and `add_log()` relies solely on a hardcoded pricing table (only 2 OpenRouter models priced).
2. **OmniRoute** does not return a per-response cost; it computes cost internally. The pricing table had zero OmniRoute entries, so all OmniRoute requests fall back to `$0.00`.
3. Historical rows for both sources have `cost_usd = NULL` or `0` because pricing was added after logging began.

## Solution

1. Extend `SidecarUsage` with an optional `cost_usd: float | None` field and read `usage.cost` in `extract_usage()`.
2. Add a `cost_usd: float | None` parameter to `RequestLogsRepository.add_log()`. Persist the passed cost; only fall back to the pricing table when `None`.
3. Wire `_log_openrouter_request()` to pass `usage.cost_usd` (authoritative).
4. Wire `_log_omniroute_request()` to pass `usage.cost_usd` (will be `None`, triggering pricing-table fallback).
5. Add common OpenRouter and OmniRoute model entries to `DEFAULT_PRICING_MODELS` and matching aliases to `DEFAULT_MODEL_ALIASES`.
6. Create an Alembic migration to backfill historical `request_logs` rows for both sources where `cost_usd IS NULL OR cost_usd == 0`, using the pricing table (authoritative per-row cost is not retroactively available for OpenRouter).

## Impact

- OpenRouter requests immediately show real cost from `usage.cost` (authoritative).
- OmniRoute requests show non-zero cost for models present in the pricing table.
- Reports totals and Request Logs reflect non-zero historical cost after migration.
- No frontend changes needed; `formatCurrency(request.costUsd)` already renders once a value is stored.

## Non-goals

- Calling OmniRoute's `/api/usage/request-logs` or `/api/pricing` endpoints.
- Rewriting the Claude sidecar cost path (already fixed).
- Frontend visual redesign.