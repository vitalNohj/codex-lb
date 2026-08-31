# dashboard-sidecar-management (delta)

## ADDED Requirements

### Requirement: Accept CLIProxyAPI weighted-round-robin routing

codex-lb MUST accept `weighted_round_robin` as a CLIProxyAPI routing strategy on `GET /api/claude-sidecar/routing` and `PUT /api/claude-sidecar/routing/strategy`. It MUST map dashboard `weighted_round_robin` to CLIProxyAPI wire value `weighted-round-robin` and MUST map that wire value back on read. It MUST still reject values other than `round_robin`, `fill_first`, and `weighted_round_robin` before calling upstream.

#### Scenario: Weighted-round-robin strategy is returned on read

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **AND** CLIProxyAPI returns `weighted-round-robin` from `GET /v0/management/routing/strategy`
- **WHEN** an operator requests `GET /api/claude-sidecar/routing`
- **THEN** codex-lb responds with `status="healthy"`
- **AND** the response contains `strategy="weighted_round_robin"`

#### Scenario: Weighted-round-robin strategy update succeeds

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/strategy` with `strategy="weighted_round_robin"`
- **THEN** codex-lb calls `PUT /v0/management/routing/strategy` with `value="weighted-round-robin"`
- **AND** codex-lb responds with the refreshed routing state
