# Context

## Purpose

Surface how much money codex-lb saves by routing to free/cheap sidecar models, instead of only recording `cost_usd = 0.00`. The "savings" is the difference between what the request actually cost and what the same token usage would have cost on the paid-equivalent model.

## Key decisions

- **Storage**: new nullable `request_logs.reference_cost_usd` column, computed at dispatch time. Per-request, aggregatable, and stable against later price changes. Savings is derived (`reference_cost_usd - cost_usd`) rather than stored.
- **Pricing source**: parse the `pricing` object already present in the OpenRouter sidecar `/models` response (already fetched and TTL-cached in `OpenRouterSidecarClient`). No new outbound egress.
- **Free->paid resolution**: strip the free marker (`:free`/`-free`/`_free`, reusing the existing free-model regex shape) and look up the paid variant in the runtime registry, falling back to the static table.
- **Actual cost unchanged**: `cost_usd` remains authoritative spend; free requests still record `$0.00`. Reference cost is purely additive.

## Constraints / failure modes

- OpenRouter pricing values are decimal *strings* per token and may be `"0"`; parse defensively and convert per-token -> per-1M (x1,000,000).
- If a model has no resolvable reference price, `reference_cost_usd` stays NULL and the row contributes nothing to savings (no misleading zeros).
- The static `DEFAULT_PRICING_MODELS` table remains an offline fallback so reference cost still works when the sidecar models endpoint is unavailable.

## Example

A request to `vendor/model-x:free` consuming 10k input + 2k output tokens, where `vendor/model-x` lists `prompt=$0.0000008/tok`, `completion=$0.000004/tok`:

- `cost_usd = 0.00`
- `reference_cost_usd = 10000 * 0.8/1e6 + 2000 * 4.0/1e6 = 0.008 + 0.008 = 0.016`
- `savings_usd = 0.016`
