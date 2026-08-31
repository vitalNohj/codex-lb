# frontend-architecture (delta)

## ADDED Requirements

### Requirement: CLIProxyAPI routing dropdown includes weighted round robin

The CLIProxyAPI routing-strategy dropdown MUST offer Weighted round robin as a selectable value that sends `weighted_round_robin` to `PUT /api/claude-sidecar/routing/strategy`. When the routing query returns `strategy="weighted_round_robin"`, the dropdown MUST show that value as selected. Help copy MUST state that weighted round robin mixes requests by each auth file's integer `weight` inside the top priority group and that omitted weights default to 1.

#### Scenario: Operator can select weighted round robin

- **GIVEN** the CLIProxyAPI integration card is rendered with a configured Management API key
- **WHEN** an operator opens the routing-strategy dropdown
- **THEN** Weighted round robin is listed alongside Round robin and Fill first
- **AND** choosing Weighted round robin calls the routing strategy update endpoint with `strategy="weighted_round_robin"`

#### Scenario: Live weighted-round-robin strategy is shown

- **GIVEN** the CLIProxyAPI integration card is rendered with a configured Management API key
- **AND** the routing query returns `strategy="weighted_round_robin"`
- **WHEN** the Settings page is displayed
- **THEN** the routing-strategy dropdown shows Weighted round robin as the current value
