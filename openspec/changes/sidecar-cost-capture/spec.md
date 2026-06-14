# Sidecar Cost Capture — Delta Spec

## Scope

This change modifies how `cost_usd` is computed and persisted for `request_logs` rows originating from the OpenRouter and OmniRoute sidecars. It does not affect the Claude sidecar, direct account traffic, or any other source.

## Requirements

### REQ-01: Authoritative OpenRouter cost capture
**The system SHALL capture and persist the `usage.cost` field returned by the OpenRouter API for every OpenRouter sidecar request.**

- Rationale: OpenRouter returns an authoritative per-request cost in credits in every response. This is more accurate than a local pricing table lookup.
- Verification: A successful OpenRouter chat completion request results in a `request_logs` row with `source = 'openrouter_sidecar'` and `cost_usd` equal to the API's `usage.cost` value (converted from credits to USD if applicable).

### REQ-02: Pricing-table fallback for OmniRoute
**When the OmniRoute sidecar response does not contain a cost field, the system SHALL fall back to the local pricing table to compute `cost_usd` at insert time.**

- Rationale: OmniRoute does not return a per-response cost; it computes cost internally. The pricing table is the only available source.
- Verification: An OmniRoute request for a model present in `DEFAULT_PRICING_MODELS` results in a non-zero `cost_usd`. An OmniRoute request for an unknown model results in `cost_usd = NULL`.

### REQ-03: Authoritative cost takes precedence over pricing table
**When both an authoritative cost from the API response and a pricing-table match exist, the authoritative cost SHALL be persisted and the pricing table SHALL NOT be consulted for that row.**

- Rationale: The API's own cost calculation uses the model's native tokenizer and up-to-date rates. The local table may be stale or use a different tokenizer.
- Verification: `add_log(..., cost_usd=0.12)` persists `0.12` even if the pricing table would have computed `0.10`.

### REQ-04: Backfill historical rows
**Historical `request_logs` rows for `openrouter_sidecar` and `omniroute_sidecar` sources where `cost_usd IS NULL OR cost_usd == 0` SHALL be recomputed using the current pricing table.**

- Rationale: Pricing entries were added after logging began. Backfill ensures Reports totals reflect past usage.
- Verification: After migration, `SELECT COUNT(*) FROM request_logs WHERE source IN ('openrouter_sidecar','omniroute_sidecar') AND (cost_usd IS NULL OR cost_usd == 0)` returns 0 for models present in the pricing table.

### REQ-05: No regression for other sources
**The `cost_usd` behavior for `claude_sidecar`, direct account traffic, and all other sources SHALL remain unchanged.**

- Verification: Existing tests for those paths pass without modification.

## Data Model Changes

### `SidecarUsage` (app/modules/proxy/claude_sidecar_dispatch.py)
- Added field: `cost_usd: float | None = None`

### `RequestLogsRepository.add_log()` (app/modules/request_logs/repository.py)
- Added parameter: `cost_usd: float | None = None`
- Behavior: if `cost_usd is not None`, persist it directly; else compute from pricing table.

### `DEFAULT_PRICING_MODELS` (app/core/usage/pricing.py)
- Added ~20 entries covering common OpenRouter models (provider/model format) and OmniRoute models (bare names).

### `DEFAULT_MODEL_ALIASES` (app/core/usage/pricing.py)
- Added glob patterns mapping common model identifiers to the above pricing entries.

## Migration

- Revision: `20260614_000000_backfill_openrouter_omniroute_request_log_costs`
- Revises: `20260612_000000_add_omniroute_sidecar_dashboard_settings` (current head)
- Single-head upgrade path maintained.
- `downgrade()` sets `cost_usd = NULL` for affected rows.

## Non-Functional

- No new external dependencies.
- No schema migrations beyond the backfill data update (no column changes).
- Frontend unchanged; existing `formatCurrency(request.costUsd)` renders the stored value.