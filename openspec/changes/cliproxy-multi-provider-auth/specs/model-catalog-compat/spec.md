# model-catalog-compat (delta)

## ADDED Requirements

### Requirement: Label and own CLIProxyAPI catalog models without Claude-only hardcoding for non-Claude ids

When CLIProxyAPI-discovered or CLIProxyAPI-configured models are merged into OpenAI-compatible `GET /v1/models` and dashboard model listings, codex-lb MUST classify each model as Claude vs non-Claude using available model-id / provider signals, and MUST NOT hard-label every CLIProxyAPI model as Claude or set `owned_by` to `anthropic` for non-Claude models. Non-Claude CLIProxyAPI models MUST use a neutral CLIProxyAPI display label (for example `CLIProxyAPI: <id>`) and a non-Anthropic `owned_by` value (for example `cliproxyapi` or a provider-accurate owner). Claude-classified CLIProxyAPI models MAY keep Claude-accurate labeling.

#### Scenario: Grok model is not labeled as Claude on GET /v1/models

- **GIVEN** the CLIProxyAPI sidecar is enabled
- **AND** CLIProxyAPI models or configured full-models include a Grok/xAI model id
- **WHEN** a client fetches `GET /v1/models`
- **THEN** that Grok/xAI model entry is present
- **AND** its display metadata does not claim the model is Claude
- **AND** `owned_by` is not `anthropic`

#### Scenario: Grok model is not labeled as Claude on dashboard model list

- **GIVEN** the CLIProxyAPI sidecar is enabled
- **AND** discovered CLIProxyAPI models include a Grok/xAI model id
- **WHEN** the dashboard models API builds its sidecar model entries
- **THEN** that entry is not prefixed or titled as `Claude: <id>`
- **AND** the underlying model id remains available to operators/clients

#### Scenario: Claude model labeling remains accurate

- **GIVEN** a Claude model id is present from CLIProxyAPI
- **WHEN** model listings include that id
- **THEN** the entry may use Claude-accurate labeling
- **AND** the listing still exposes the underlying model id
