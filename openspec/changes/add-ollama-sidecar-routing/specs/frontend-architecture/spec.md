## ADDED Requirements

### Requirement: Expose Ollama in external integrations tabs

Settings MUST expose an Ollama Integration tab inside the existing "External Integrations" card with enable toggle, API key field, base URL, prefixes, full models, discovered models, timeouts, and status. The implementation MUST add an `OllamaSidecarSettings` component accepting `bare?: boolean` and exactly one Ollama entry to the existing `tabs` array in `sidecar-integrations.tsx`.

The implementation MUST NOT create a new top-level Settings card for Ollama and MUST NOT restructure the existing external integrations card, tab list, tab trigger, or tab content layout. Ollama conflict detection MUST use the same cross-integration prefix and full-model checks as the existing sidecar integrations.

#### Scenario: Ollama appears as a tab

- **WHEN** an authenticated operator opens Settings
- **THEN** the "External Integrations" card includes tabs for CLIProxyAPI, OpenRouter, OmniRoute, and Ollama
- **AND** selecting the Ollama tab shows `Ollama Integration`

#### Scenario: Enabled Ollama can be the default active tab

- **GIVEN** only the Ollama sidecar integration is enabled
- **WHEN** an authenticated operator opens Settings
- **THEN** the Ollama tab is active by default

#### Scenario: Discovered non-cloud models are hidden

- **GIVEN** Ollama model discovery returns `llama3.2` and `gpt-oss:120b-cloud`
- **WHEN** an authenticated operator opens the Ollama discovered-model browser
- **THEN** `gpt-oss:120b-cloud` is available
- **AND** `llama3.2` is hidden

#### Scenario: Discovered cloud model can be added as direct full model

- **GIVEN** Ollama model discovery returns `gpt-oss:120b-cloud`
- **WHEN** an authenticated operator adds that discovered model from the Ollama tab
- **THEN** the settings save payload includes `ollamaSidecarFullModels` containing `gpt-oss:120b-cloud`

#### Scenario: Manual prefix can be added

- **WHEN** an authenticated operator types an Ollama prefix and saves it from the Ollama tab
- **THEN** the settings save payload includes the prefix in `ollamaSidecarModelPrefixes`

#### Scenario: Duplicate sidecar routes are rejected inline

- **GIVEN** OpenRouter already owns prefix `open/`
- **WHEN** an authenticated operator tries to add prefix `open/` in the Ollama tab
- **THEN** the Ollama tab shows an inline conflict
- **AND** the duplicate route is not persisted
