# api-keys (delta)

## ADDED Requirements

### Requirement: Claude model pricing is recognized

The system MUST recognize Anthropic Claude model pricing when computing
request costs (`cost_usd`), including date-suffixed model ids
(e.g. `claude-opus-4-5-20251101`) and sidecar-prefixed model ids that embed
a known Claude model name (e.g. `cp-claude-fable-5`). Cache-read tokens MUST
be priced at the published cache-hit rate for the resolved model.

#### Scenario: Canonical Claude model resolves pricing

- **WHEN** a request log records model `claude-sonnet-4-6` with token usage
- **THEN** `cost_usd` is computed from the Sonnet 4.6 published rates

#### Scenario: Date-suffixed Claude model resolves pricing

- **WHEN** a request log records model `claude-opus-4-5-20251101`
- **THEN** `cost_usd` is computed from the Opus 4.5 published rates

#### Scenario: Sidecar-prefixed Claude model resolves pricing

- **WHEN** a sidecar request log records model `cp-claude-fable-5`
- **THEN** `cost_usd` is computed from the Fable 5 published rates

### Requirement: Historical sidecar request logs are backfilled with cost

A database migration MUST recompute `cost_usd` for existing
`request_logs` rows with `source = 'claude_sidecar'` and `cost_usd IS NULL`
using the recognized Claude pricing, so dollar reports reflect historical
sidecar usage.

#### Scenario: Backfill populates cost for prior sidecar traffic

- **GIVEN** a pre-existing sidecar request log with token usage and
  `cost_usd IS NULL`
- **WHEN** the migration runs
- **THEN** the row's `cost_usd` is set from the resolved Claude pricing
