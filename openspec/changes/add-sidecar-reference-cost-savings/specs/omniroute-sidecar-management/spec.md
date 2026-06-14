## ADDED Requirements

### Requirement: OmniRoute sidecar requests record reference cost when pricing is resolvable

For OmniRoute sidecar requests, the system MUST compute and persist a reference cost (`reference_cost_usd`) representing what the request would have cost at the paid-equivalent list price, using the runtime reference-pricing lookup and the request's actual token usage. When no reference price can be resolved for the request's model, `reference_cost_usd` MUST be left unset.

#### Scenario: Reference cost is recorded for a resolvable model
- **WHEN** an OmniRoute sidecar request completes with usage tokens
- **AND** a reference price can be resolved for the effective model
- **THEN** the request log persists `reference_cost_usd` computed from the resolved reference price and the actual usage tokens

#### Scenario: Reference cost is omitted when pricing is unresolvable
- **WHEN** an OmniRoute sidecar request completes
- **AND** no reference price can be resolved for the effective model
- **THEN** the request log leaves `reference_cost_usd` unset
- **AND** the actual `cost_usd` value is unchanged
