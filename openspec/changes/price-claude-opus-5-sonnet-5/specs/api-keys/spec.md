## ADDED Requirements

### Requirement: Claude Opus 5 and Sonnet 5 pricing is recognized

The system MUST recognize Anthropic Claude Opus 5 and Claude Sonnet 5 when computing request costs (`cost_usd`), including sidecar-prefixed ids such as `cc/claude-opus-5` and `cp-claude-sonnet-5`. Cache-read tokens MUST be priced at the published cache-hit rate for the resolved model.

#### Scenario: Canonical Opus 5 model resolves pricing

- **WHEN** a request log records model `claude-opus-5` with token usage
- **THEN** `cost_usd` is computed from the Opus 5 published rates ($5 input / $0.50 cache-hit / $25 output per 1M tokens)

#### Scenario: Sidecar-prefixed Opus 5 model resolves pricing

- **WHEN** a sidecar request log records model `cc/claude-opus-5` with token usage
- **THEN** `cost_usd` is computed from the Opus 5 published rates
- **AND** the system does not leave `cost_usd` NULL

#### Scenario: Canonical Sonnet 5 model resolves pricing

- **WHEN** a request log records model `claude-sonnet-5` with token usage
- **THEN** `cost_usd` is computed from the Sonnet 5 published rates ($2 input / $0.20 cache-hit / $10 output per 1M tokens)

#### Scenario: Sidecar-prefixed Sonnet 5 model resolves pricing

- **WHEN** a sidecar request log records model `cc/claude-sonnet-5` with token usage
- **THEN** `cost_usd` is computed from the Sonnet 5 published rates

### Requirement: Historical Opus 5 and Sonnet 5 sidecar request logs are backfilled with cost

A database migration MUST recompute `cost_usd` for existing `request_logs` rows with `source = 'claude_sidecar'` and `cost_usd IS NULL` using the recognized Claude pricing, so dollar reports include historical Opus 5 and Sonnet 5 sidecar usage.

#### Scenario: Backfill populates cost for prior Opus 5 sidecar traffic

- **GIVEN** a pre-existing sidecar request log with model `cc/claude-opus-5`, token usage, and `cost_usd IS NULL`
- **WHEN** the migration runs
- **THEN** the row's `cost_usd` is set from the resolved Opus 5 pricing

#### Scenario: Backfill leaves unknown sidecar models as unknown cost

- **GIVEN** a pre-existing sidecar request log whose model still has no pricing entry
- **WHEN** the migration runs
- **THEN** that row's `cost_usd` remains NULL
