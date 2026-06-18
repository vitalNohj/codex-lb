## ADDED Requirements

### Requirement: Sidecar routable models are advertised uniformly per integration

The OpenAI-compatible model catalog SHALL advertise routable sidecar models for every enabled integration using the same uniform rules: each integration's configured full-model list entries SHALL be advertised as routable model IDs, regardless of which integration owns them. The catalog SHALL not advertise prefixes themselves as models; prefixes only describe how arbitrary client model IDs are matched at request time.

When the same model text could be produced by more than one integration's configuration, the catalog SHALL list it once, attributed to the integration that owns it under the unified routing precedence (full-model exact match before longest-prefix match).

#### Scenario: Full models from each integration are advertised

- **GIVEN** CLIProxyAPI has full model `cp-claude-sonnet-4`
- **AND** OmniRoute has full model `minimax/minimax-m3`
- **WHEN** a client requests the model catalog
- **THEN** the catalog includes both `cp-claude-sonnet-4` and `minimax/minimax-m3` as routable models

#### Scenario: Disabled integration models are not advertised

- **GIVEN** OpenRouter is disabled with full model `deepseek/deepseek-chat`
- **WHEN** a client requests the model catalog
- **THEN** the catalog does not advertise `deepseek/deepseek-chat`
```
