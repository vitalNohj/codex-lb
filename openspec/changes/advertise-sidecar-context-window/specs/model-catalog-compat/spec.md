## ADDED Requirements

### Requirement: Sidecar models advertise a context window on /v1/models

When serving `GET /v1/models`, the system SHALL expose an input context window
for sidecar models (Claude/cliproxyapi `cp-*`, OpenRouter, and OmniRoute) so
OpenAI-compatible clients (such as Cursor's local-provider discovery) can learn
the window and trigger their own conversation compaction instead of relying on
provider-side context overflow failures. Each sidecar model entry MUST include
`context_length`, `contextLength`, and `capabilities.context_length`, all set to
the advertised window. The advertised default window for sidecar models SHALL be
`200000`.

#### Scenario: Claude sidecar model exposes the context window

- **WHEN** a Claude sidecar model `claude-sonnet-4-5-20250929` is returned by `GET /v1/models`
- **THEN** the entry includes `context_length=200000`
- **AND** `contextLength=200000`
- **AND** `capabilities.context_length=200000`

#### Scenario: OpenRouter sidecar model exposes the context window

- **WHEN** an OpenRouter sidecar model `deepseek/deepseek-chat` is returned by `GET /v1/models`
- **THEN** the entry includes `context_length=200000`
- **AND** `capabilities.context_length=200000`

#### Scenario: OmniRoute sidecar model exposes the context window

- **WHEN** an OmniRoute sidecar model `omniroute/test-chat` is returned by `GET /v1/models`
- **THEN** the entry includes `context_length=200000`
- **AND** `capabilities.context_length=200000`

#### Scenario: Registry model context metadata is unchanged

- **WHEN** a registry GPT-5 Codex model with `context_window=272000` is returned by `GET /v1/models`
- **THEN** the entry continues to report `context_length=272000` from its backend context window
