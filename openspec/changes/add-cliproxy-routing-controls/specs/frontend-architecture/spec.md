# frontend-architecture (delta)

## ADDED Requirements

### Requirement: CLIProxyAPI card routing controls

The CLIProxyAPI integration card MUST render routing controls only when a CLIProxyAPI Management API key is configured. When visible, the controls MUST include a routing-strategy dropdown, a per-account priority list, and copy that makes clear a higher numeric priority is preferred.

#### Scenario: Controls are hidden without a management key

- **GIVEN** the CLIProxyAPI integration card is rendered without a configured Management API key
- **WHEN** the Settings page is displayed
- **THEN** the routing-strategy dropdown is not shown
- **AND** per-account priority controls are not shown

#### Scenario: Strategy change persists immediately

- **GIVEN** the CLIProxyAPI integration card is rendered with a configured Management API key
- **AND** the routing query has loaded the current strategy
- **WHEN** an operator selects a different strategy in the routing dropdown
- **THEN** the frontend calls the routing strategy update endpoint immediately
- **AND** it invalidates or refreshes the routing query after the mutation settles

#### Scenario: Priority edit commits on blur or Enter

- **GIVEN** the CLIProxyAPI integration card is rendered with a configured Management API key
- **AND** the routing query has loaded account priorities
- **WHEN** an operator changes an account priority input and blurs the input or presses Enter
- **THEN** the frontend calls the account priority update endpoint with the auth-file name and numeric priority
- **AND** it invalidates or refreshes the routing query after the mutation settles
