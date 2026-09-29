# frontend-architecture (delta)

## ADDED Requirements

### Requirement: Global CLIProxyAPI session affinity switch

The Accounts Claude detail MUST show one Session affinity switch in the global area above the per-account list, and the Settings CLIProxyAPI routing panel MUST show one Session affinity switch next to Routing strategy. The switch MUST NOT appear on an account row. When routing is healthy, the switch MUST reflect `sessionAffinity` and a change MUST call `PUT /api/claude-sidecar/routing/session-affinity` with that boolean. The switch MUST stay disabled while routing is not healthy. A non-healthy write response MUST show the routing message and MUST NOT replace the healthy routing state.

#### Scenario: Accounts page shows one global switch

- **GIVEN** the Accounts Claude detail lists more than one CLIProxyAPI account
- **AND** the routing query is healthy with `sessionAffinity=false`
- **WHEN** the Accounts page is displayed
- **THEN** one Session affinity switch is shown above the account list
- **AND** that switch is off
- **AND** no account row contains a Session affinity switch

#### Scenario: Turning the switch on updates the global flag

- **GIVEN** the CLIProxyAPI routing panel is rendered with a healthy routing query
- **AND** `sessionAffinity=false`
- **WHEN** an operator turns Session affinity on
- **THEN** the client calls `PUT /api/claude-sidecar/routing/session-affinity` with `sessionAffinity=true`

#### Scenario: A failed write shows the routing message

- **GIVEN** the CLIProxyAPI routing panel is rendered with a healthy routing query
- **AND** `sessionAffinity=false`
- **WHEN** an operator turns Session affinity on
- **AND** the update responds with `status="error"` and a message
- **THEN** the client shows that message
- **AND** the Session affinity switch stays off

#### Scenario: A healthy on flag is shown as on

- **GIVEN** the CLIProxyAPI routing panel is rendered with a healthy routing query
- **AND** `sessionAffinity=true`
- **WHEN** the Settings page is displayed
- **THEN** the Session affinity switch is on
