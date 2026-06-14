## Why

When codex-lb routes a request to a free OpenRouter/OmniRoute model, the sidecar reports `usage.cost = 0`, so the request log persists `cost_usd = 0.00`. That is accurate as *spend*, but it discards the value of the savings: the same tokens would have cost real money on the equivalent paid model. Operators want to see how much they are saving, not just that they paid nothing.

The static pricing table (`DEFAULT_PRICING_MODELS`) cannot cover every model, especially newly released ones, so the reference price for "what this would have cost" must be retrievable at runtime. OpenRouter already returns a per-model `pricing` object in its `/models` response, which codex-lb currently fetches (and caches) but discards.

## What Changes

- Parse the `pricing` object from the OpenRouter sidecar `/models` response into model pricing (per-token USD converted to per-1M tokens), and carry it on the fetched model entries.
- Add a runtime model-pricing registry that overlays live OpenRouter pricing on top of the static `DEFAULT_PRICING_MODELS` table, used only for reference-cost lookups (actual-cost behavior is unchanged).
- Resolve a free model's paid equivalent by stripping the `:free` / `-free` / `_free` marker and looking up the paid variant's runtime pricing.
- Add a nullable `request_logs.reference_cost_usd` column capturing what the request would have cost at the paid-equivalent list price, computed at dispatch time from actual token usage.
- Compute and persist `reference_cost_usd` for OpenRouter and OmniRoute sidecar requests.
- Surface reference cost and derived savings (`reference_cost_usd - cost_usd`) in request-log serialization, usage aggregation, and the dashboard.

## Non-goals

- Do not change how actual `cost_usd` is computed or persisted; free requests still record `$0.00`.
- Do not add a new outbound egress path; reference pricing comes from the already-fetched sidecar `/models` response.
- Do not backfill historical rows in this change (may be a follow-up).
- Do not change OmniRoute model fetching beyond reusing reference pricing when available; OmniRoute reference cost relies on whatever pricing the registry can resolve.

## Capabilities

### Modified Capabilities

- `openrouter-sidecar-management`: parse and expose OpenRouter model pricing at runtime for reference-cost lookups.
- `omniroute-sidecar-management`: compute and persist reference cost / savings for OmniRoute sidecar requests using resolvable runtime pricing.
- `proxy-runtime-observability`: persist `reference_cost_usd` on request logs and expose savings in usage aggregation and request-log serialization.
- `frontend-architecture`: display sidecar savings on the dashboard.

## Impact

- `app/core/clients/openrouter_sidecar.py`: parse `pricing` from `/models`.
- `app/core/clients/claude_sidecar.py` (`SidecarModel`): carry parsed pricing.
- New runtime pricing registry under `app/core/usage/`.
- `app/db/models.py` + new Alembic migration: `reference_cost_usd` column.
- `app/modules/request_logs/repository.py` (`add_log`) and dispatch helpers for OpenRouter/OmniRoute.
- `app/modules/request_logs/schemas.py`, usage aggregation, `app/modules/dashboard/service.py`.
- Frontend dashboard surfaces and tests.
