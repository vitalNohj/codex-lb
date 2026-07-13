# model-catalog-compat (delta)

## ADDED Requirements

### Requirement: Label CLIProxyAPI catalog models without Claude-only hardcoding for non-Claude ids

When CLIProxyAPI-discovered or CLIProxyAPI-configured models are merged into OpenAI-compatible `GET /v1/models` and dashboard model listings, codex-lb MUST NOT hard-label every CLIProxyAPI model as Claude. Non-Claude CLIProxyAPI models (including Grok/xAI) MUST use a neutral CLIProxyAPI label or a provider-accurate label derived from known provider classification, while Claude models MAY keep a Claude-accurate label.

#### Scenario: Grok model is not labeled as Claude

- **GIVEN** the CLIProxyAPI sidecar is enabled
- **AND** the CLIProxyAPI model list or configured full-models include a Grok/xAI model id
- **WHEN** a client fetches `GET /v1/models` or the dashboard models list that includes sidecar models
- **THEN** that Grok/xAI model entry is present
- **AND** its display label does not claim the model is Claude

#### Scenario: Claude model labeling remains accurate

- **GIVEN** the CLIProxyAPI sidecar is enabled
- **AND** a Claude model id is present from CLIProxyAPI
- **WHEN** model listings include that id
- **THEN** the entry may be labeled as Claude or CLIProxyAPI
- **AND** the listing still exposes the underlying model id for clients
