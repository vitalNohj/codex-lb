# dashboard-sidecar-management (delta)

## ADDED Requirements

### Requirement: Read and write global CLIProxyAPI session affinity

codex-lb MUST expose CLIProxyAPI `routing.session-affinity` as a global `sessionAffinity` boolean on `GET /api/claude-sidecar/routing` and `PUT /api/claude-sidecar/routing/session-affinity`. A missing upstream `session-affinity` value MUST be reported as false. The update MUST persist only the direct `routing.session-affinity` flag and MUST leave every other config key unchanged, including a nested `session-affinity` key, `session-affinity-ttl`, and `session-affinity-subagents`. The update MUST NOT upload a snapshot after the config file has changed, and it MUST fail without uploading when the file still changes across three read pairs. The update MUST NOT take an account name.

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

#### Scenario: A final routing header without a newline stays a mapping

- **GIVEN** the persisted config is the single line `routing:` with no trailing newline
- **WHEN** an operator turns session affinity on
- **THEN** the uploaded document is a `routing` block
- **AND** its direct `session-affinity` value is true

#### Scenario: A nested session-affinity key is not the routing flag

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **AND** the persisted config has a nested `session-affinity: false` before the direct `routing.session-affinity: false`
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/session-affinity` with `sessionAffinity=true`
- **THEN** the uploaded document sets the direct `routing.session-affinity` value to true
- **AND** the nested `session-affinity` value is still false

#### Scenario: A changed config snapshot is not uploaded

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **AND** the config file changes between the first and second download
- **AND** the next two downloads are identical and contain `debug: true`
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/session-affinity` with `sessionAffinity=true`
- **THEN** the uploaded document contains `debug: true` and `session-affinity: true`
- **AND** the uploaded document does not contain the earlier snapshot

#### Scenario: A config that keeps changing is not uploaded

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **AND** every config download differs from the previous download
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/session-affinity` with `sessionAffinity=true`
- **THEN** codex-lb does not upload a config
- **AND** the routing response status is `error`

#### Scenario: Session affinity update does not accept an account

- **GIVEN** CLIProxyAPI routing is enabled and a Management API key is configured
- **WHEN** an operator sends `PUT /api/claude-sidecar/routing/session-affinity` with an account name and no `sessionAffinity` boolean
- **THEN** codex-lb rejects the body before calling CLIProxyAPI
