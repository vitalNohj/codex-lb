# chat-completions-compat (delta)

## ADDED Requirements

### Requirement: Dispatch CLIProxyAPI-matched Grok models through the existing sidecar path

The service MUST dispatch Chat Completions requests whose effective model matches the CLIProxyAPI integration's configured full-models or prefixes to the existing CLIProxyAPI sidecar dispatch path, including Grok/xAI model ids, and MUST apply the same effective-vs-wire model split, reservation settlement, and request-log source behavior already used for CLIProxyAPI-routed Claude models. Multi-provider CLIProxyAPI auth support MUST NOT require a separate chat-completions dispatcher for Grok.

#### Scenario: Grok full-model match routes to CLIProxyAPI

- **GIVEN** the CLIProxyAPI sidecar integration is enabled
- **AND** CLIProxyAPI full-models include a Grok/xAI model id
- **WHEN** a client sends `POST /v1/chat/completions` with that model
- **THEN** the service routes the request to the CLIProxyAPI sidecar
- **AND** no native Codex account is selected for the request
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
- **THEN** the service does not route the request to CLIProxyAPI solely because the name contains `grok`
- **AND** existing non-sidecar resolution rules apply
