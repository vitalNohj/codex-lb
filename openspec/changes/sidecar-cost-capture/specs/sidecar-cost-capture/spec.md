## ADDED Requirements

### Requirement: Authoritative OpenRouter cost capture

The system SHALL capture and persist the `usage.cost` field returned by the OpenRouter API for every OpenRouter sidecar request.

#### Scenario: OpenRouter request stores authoritative cost
- **WHEN** an OpenRouter sidecar chat-completions request completes successfully
- **AND** the OpenRouter response includes `usage.cost`
- **THEN** the resulting `request_logs` row has `source = "openrouter_sidecar"`
- **AND** `cost_usd` equals the API's `usage.cost` value
- **AND** the local pricing table is NOT consulted for this row

### Requirement: Pricing-table fallback for OmniRoute

When the OmniRoute sidecar response does not contain a cost field, the system SHALL fall back to the local pricing table to compute `cost_usd` at insert time.

#### Scenario: OmniRoute request uses pricing table
- **WHEN** an OmniRoute sidecar chat-completions request completes successfully
- **AND** the OmniRoute response does not include `usage.cost`
- **AND** the effective model exists in `DEFAULT_PRICING_MODELS` (via exact match or alias)
- **THEN** the resulting `request_logs` row has `source = "omniroute_sidecar"`
- **AND** `cost_usd` equals the pricing-table computed value
- **AND** `cost_usd` is non-zero for priced models

#### Scenario: OmniRoute unknown model remains zero cost
- **WHEN** an OmniRoute sidecar request completes for a model not in `DEFAULT_PRICING_MODELS` or aliases
- **THEN** the resulting `request_logs` row has `cost_usd = NULL`

### Requirement: Authoritative cost takes precedence over pricing table

When both an authoritative cost from the API response and a pricing-table match exist, the authoritative cost SHALL be persisted and the pricing table SHALL NOT be consulted for that row.

#### Scenario: Authoritative cost wins over pricing table
- **WHEN** `add_log` is called with a non-None `cost_usd` parameter
- **THEN** the persisted `cost_usd` equals the passed value
- **AND** `calculated_cost_from_log` is not invoked for that row

### Requirement: Historical rows backfilled for both sidecars

Historical `request_logs` rows for `openrouter_sidecar` and `omniroute_sidecar` sources where `cost_usd IS NULL OR cost_usd == 0` SHALL be recomputed using the current pricing table.

#### Scenario: Migration backfills historical costs
- **WHEN** the Alembic migration `20260614_000000_backfill_openrouter_omniroute_request_log_costs` runs
- **THEN** all qualifying rows for both sources are updated with computed costs
- **AND** rows where no pricing match exists retain `cost_usd = NULL`

### Requirement: No regression for other sources

The `cost_usd` behavior for `claude_sidecar`, direct account traffic, and all other sources SHALL remain unchanged.

#### Scenario: Existing sources unchanged
- **WHEN** a non-sidecar request is logged
- **THEN** `cost_usd` is computed from the pricing table as before
- **AND** no new parameters are required at call sites

## MODIFIED Requirements

### Requirement: Request logging captures sidecar usage

The request logging system MUST accept an optional authoritative cost value from sidecar dispatchers and persist it when provided.

#### Scenario: Sidecar dispatcher passes authoritative cost
- **WHEN** `_log_openrouter_request` calls `repo.add_log`
- **THEN** it includes `cost_usd=usage.cost_usd`
- **AND** the `SidecarUsage` object carries the cost from `extract_usage`