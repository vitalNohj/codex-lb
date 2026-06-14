## ADDED Requirements

### Requirement: Request logs persist reference cost and expose savings

The system MUST persist a nullable `reference_cost_usd` value on request logs representing what the request would have cost at the paid-equivalent list price. The actual `cost_usd` value MUST remain the authoritative record of spend and MUST be unchanged by this behavior. Request-log serialization MUST expose `reference_cost_usd` and a derived `savings_usd` value computed as `reference_cost_usd - cost_usd` when both values are available; when reference cost is unavailable, `savings_usd` MUST be unset.

#### Scenario: Free request records savings against paid-equivalent price
- **WHEN** a sidecar request was served by a free model whose paid equivalent has a resolvable reference price
- **AND** the actual `cost_usd` recorded is `0.00`
- **THEN** the request log persists a positive `reference_cost_usd`
- **AND** serialization exposes `savings_usd` equal to `reference_cost_usd - cost_usd`

#### Scenario: Savings is unset when reference cost is unavailable
- **WHEN** a request log has no `reference_cost_usd`
- **THEN** serialization leaves `savings_usd` unset

### Requirement: Usage aggregation exposes total savings

Usage aggregation that reports total cost MUST also report total reference cost and total savings across the aggregated request logs, where total savings is the sum of per-request savings for rows that have a reference cost. Rows without a reference cost MUST NOT contribute to total savings.

#### Scenario: Aggregated savings sums per-request savings
- **WHEN** usage aggregation runs over request logs where some rows have a `reference_cost_usd` greater than their `cost_usd`
- **THEN** the aggregated result reports total savings equal to the sum of `reference_cost_usd - cost_usd` over those rows
- **AND** rows without `reference_cost_usd` are excluded from total savings
