# dashboard-sidecar-management (delta)

## ADDED Requirements

### Requirement: Read and write global CLIProxyAPI session affinity

codex-lb MUST expose CLIProxyAPI `routing.session-affinity` as a global `sessionAffinity` boolean on `GET /api/claude-sidecar/routing` and `PUT /api/claude-sidecar/routing/session-affinity`. A missing upstream `session-affinity` value MUST be reported as false. The update MUST persist only that flag and MUST leave every other config key unchanged, including `session-affinity-ttl` and `session-affinity-subagents`. The update MUST NOT take an account name.

#### Scenario: Missing session affinity is reported as off

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **AND** `GET /v0/management/config` omits `routing.session-affinity`
- **WHEN** an operator requests `GET /api/claude-sidecar/routing`
- **THEN** codex-lb responds with `status="healthy"`
- **AND** the response contains `sessionAffinity=false`

#### Scenario: Enabled session affinity is reported as on

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **AND** `GET /v0/management/config` returns `routing.session-affinity=true`
- **WHEN** an operator requests `GET /api/claude-sidecar/routing`
- **THEN** the response contains `sessionAffinity=true`

#### Scenario: Turning session affinity on writes only that flag

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **AND** the persisted config contains `session-affinity: false` and `session-affinity-ttl: "1h"`
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/session-affinity` with `sessionAffinity=true`
- **THEN** codex-lb uploads a config whose `routing.session-affinity` value is true
- **AND** `session-affinity-ttl` is still `"1h"`
- **AND** the response contains `sessionAffinity=true`

#### Scenario: Session affinity update does not accept an account

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/session-affinity` with an account name and no `sessionAffinity` boolean
- **THEN** codex-lb rejects the body before calling CLIProxyAPI
