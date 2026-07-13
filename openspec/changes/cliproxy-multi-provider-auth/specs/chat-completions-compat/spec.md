# chat-completions-compat (delta)

## ADDED Requirements

### Requirement: Dispatch CLIProxyAPI-matched Grok models through the existing sidecar path

The service MUST dispatch Chat Completions requests whose effective model matches the CLIProxyAPI integration's configured full-models or prefixes to the existing CLIProxyAPI sidecar dispatch path, including Grok/xAI model ids, and MUST apply the same effective-vs-wire model split, reservation settlement, shared CLIProxyAPI reasoning-effort override, and request-log source key already used for CLIProxyAPI-routed requests. Multi-provider auth support MUST NOT add a separate chat-completions dispatcher or a new sidecar resolver provider id for Grok.

#### Scenario: Grok full-model match routes to CLIProxyAPI

- **GIVEN** the CLIProxyAPI sidecar integration is enabled
- **AND** CLIProxyAPI full-models include a Grok/xAI model id
- **WHEN** a client sends `POST /v1/chat/completions` with that model
- **THEN** the service routes the request to the CLIProxyAPI sidecar
- **AND** no native Codex account is selected
- **AND** the request log source remains the existing CLIProxyAPI sidecar source key

#### Scenario: Grok prefix match respects strip flag

- **GIVEN** the CLIProxyAPI sidecar integration is enabled
- **AND** a CLIProxyAPI prefix matches a Grok/xAI model id with strip enabled or disabled per configuration
- **WHEN** a client sends `POST /v1/chat/completions` with that model
- **THEN** the service routes to CLIProxyAPI
- **AND** the forwarded wire model follows the configured strip behavior
- **AND** request logs record the effective (client) model

#### Scenario: Unmatched Grok-like model does not force CLIProxyAPI

- **GIVEN** the CLIProxyAPI sidecar integration is enabled
- **AND** no CLIProxyAPI full-model or prefix matches `grok-unconfigured-model`
- **WHEN** a client sends `POST /v1/chat/completions` with `model: "grok-unconfigured-model"`
- **THEN** the service does not route to CLIProxyAPI solely because the name contains `grok`
- **AND** existing non-sidecar resolution rules apply

#### Scenario: Shared effort override still applies on CLIProxyAPI Grok dispatch

- **GIVEN** the CLIProxyAPI sidecar default reasoning-effort override is configured
- **AND** a Grok model is routed to CLIProxyAPI
- **WHEN** the outbound chat payload is built
- **THEN** the shared CLIProxyAPI effort override is applied by the existing override path
- **AND** no separate Grok-only effort setting is required for this change
