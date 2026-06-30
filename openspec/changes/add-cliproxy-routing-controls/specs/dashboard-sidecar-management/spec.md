# dashboard-sidecar-management (delta)

## ADDED Requirements

### Requirement: Read CLIProxyAPI routing configuration

codex-lb MUST expose the current CLIProxyAPI routing strategy and per-account priorities via `GET /api/claude-sidecar/routing`, fetched live through CLIProxyAPI's Management API. The response MUST report `disabled` when CLIProxyAPI routing is disabled and `not_configured` when no CLIProxyAPI Management API key is configured, without calling upstream in either case.

#### Scenario: Healthy routing state is returned

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **AND** CLIProxyAPI returns `fill-first` from `GET /v0/management/routing/strategy`
- **AND** CLIProxyAPI returns Claude auth-file entries from `GET /v0/management/auth-files`
- **WHEN** an operator requests `GET /api/claude-sidecar/routing`
- **THEN** codex-lb responds with `status="healthy"`
- **AND** the response contains `strategy="fill_first"`
- **AND** each Claude account includes its auth-file `name`, optional `authIndex`, optional `email`, and numeric `priority`
- **AND** a missing upstream `priority` field is represented as `0`

#### Scenario: Disabled routing state is reported without upstream call

- **GIVEN** CLIProxyAPI routing is disabled in codex-lb settings
- **WHEN** an operator requests `GET /api/claude-sidecar/routing`
- **THEN** codex-lb responds with `status="disabled"`
- **AND** no CLIProxyAPI Management API request is made

#### Scenario: Missing management key is reported without upstream call

- **GIVEN** CLIProxyAPI routing is enabled
- **AND** no CLIProxyAPI Management API key is configured in codex-lb settings
- **WHEN** an operator requests `GET /api/claude-sidecar/routing`
- **THEN** codex-lb responds with `status="not_configured"`
- **AND** no CLIProxyAPI Management API request is made

#### Scenario: Upstream routing read failure is classified

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **AND** CLIProxyAPI's Management API is unreachable, unauthorized, or returns another error
- **WHEN** an operator requests `GET /api/claude-sidecar/routing`
- **THEN** codex-lb responds with a routing status of `unreachable`, `unauthorized`, or `error` matching the failure class
- **AND** the response message does not expose bearer tokens

### Requirement: Update CLIProxyAPI routing strategy

codex-lb MUST forward an operator's chosen routing strategy to CLIProxyAPI's `PUT /v0/management/routing/strategy` endpoint and MUST reject any value other than `round_robin` or `fill_first` before calling upstream. codex-lb MUST map dashboard values to CLIProxyAPI wire values (`round_robin` to `round-robin`, `fill_first` to `fill-first`) and return the fresh live routing state after a successful update.

#### Scenario: Round-robin strategy update succeeds

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/strategy` with `strategy="round_robin"`
- **THEN** codex-lb calls `PUT /v0/management/routing/strategy` with `value="round-robin"`
- **AND** codex-lb responds with the refreshed routing state

#### Scenario: Fill-first strategy update succeeds

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/strategy` with `strategy="fill_first"`
- **THEN** codex-lb calls `PUT /v0/management/routing/strategy` with `value="fill-first"`
- **AND** codex-lb responds with the refreshed routing state

#### Scenario: Invalid strategy is rejected locally

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/strategy` with an unsupported strategy value
- **THEN** codex-lb rejects the request with validation failure
- **AND** no CLIProxyAPI Management API request is made

#### Scenario: Strategy update without management key reports precondition

- **GIVEN** CLIProxyAPI routing is enabled
- **AND** no CLIProxyAPI Management API key is configured in codex-lb settings
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/strategy` with `strategy="fill_first"`
- **THEN** codex-lb responds with `status="not_configured"`
- **AND** no CLIProxyAPI Management API request is made

### Requirement: Set CLIProxyAPI account priority

codex-lb MUST forward an operator-provided auth-file `name` and numeric `priority` to CLIProxyAPI's `PATCH /v0/management/auth-files/fields` endpoint so CLIProxyAPI's highest numeric priority account is preferred at runtime. codex-lb MUST keep CLIProxyAPI auth files as the source of truth and return the fresh live routing state after a successful update.

#### Scenario: Account priority update succeeds

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/priority` with `name="claude-a@example.com.json"` and `priority=100`
- **THEN** codex-lb calls `PATCH /v0/management/auth-files/fields` with that `name` and `priority`
- **AND** codex-lb responds with the refreshed routing state

#### Scenario: Unknown auth-file name is surfaced

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **AND** CLIProxyAPI returns HTTP 404 for the requested auth-file name
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/priority` with that name
- **THEN** codex-lb responds with `status="error"`
- **AND** the response message indicates that the account was not found
