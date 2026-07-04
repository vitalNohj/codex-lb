# dashboard-sidecar-management (delta)

## ADDED Requirements

### Requirement: Pause and resume a CLIProxyAPI account

codex-lb MUST let an operator pause or resume a single CLIProxyAPI Claude account by forwarding the auth-file `name` and a boolean `paused` value to CLIProxyAPI's `PATCH /v0/management/auth-files/fields` endpoint as the `disabled` field, keeping CLIProxyAPI auth files as the only source of truth and returning the fresh live routing state after a successful update.

#### Scenario: Pausing an account succeeds

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/paused` with `name="claude-a@example.com.json"` and `paused=true`
- **THEN** codex-lb calls `PATCH /v0/management/auth-files/fields` with that `name` and `disabled=true`
- **AND** codex-lb responds with the refreshed routing state

#### Scenario: Resuming an account succeeds

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **AND** the auth file `claude-a@example.com.json` currently has `disabled=true`
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/paused` with `name="claude-a@example.com.json"` and `paused=false`
- **THEN** codex-lb calls `PATCH /v0/management/auth-files/fields` with that `name` and `disabled=false`
- **AND** codex-lb responds with the refreshed routing state

#### Scenario: Pause without management key reports precondition

- **GIVEN** CLIProxyAPI routing is enabled
- **AND** no CLIProxyAPI Management API key is configured in codex-lb settings
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/paused`
- **THEN** codex-lb responds with `status="not_configured"`
- **AND** no CLIProxyAPI Management API request is made

#### Scenario: Unknown auth-file name is surfaced

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **AND** CLIProxyAPI returns HTTP 404 for the requested auth-file name
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/paused` with that name
- **THEN** codex-lb responds with `status="error"`
- **AND** the response message indicates that the account was not found

### Requirement: Report CLIProxyAPI account paused state

codex-lb MUST expose each Claude account's live `disabled` value as a boolean `paused` field in the routing response (`GET /api/claude-sidecar/routing`) and in sidecar auth account rows returned by the quota endpoint and the accounts list, so the Settings routing section, the Accounts tab, and the dashboard account card can render a Pause/Resume toggle per account.

#### Scenario: Routing response includes paused state

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **AND** CLIProxyAPI reports one auth file with `disabled=true` and one without a `disabled` field
- **WHEN** an operator requests `GET /api/claude-sidecar/routing`
- **THEN** the disabled account is reported with `paused=true`
- **AND** the account without a `disabled` field is reported with `paused=false`

#### Scenario: Sidecar auth rows include paused state

- **GIVEN** the Claude sidecar quota snapshot contains an account with `disabled=true`
- **WHEN** an operator requests the accounts list or the Claude sidecar quota endpoint
- **THEN** that account's sidecar auth row is reported with `paused=true`
