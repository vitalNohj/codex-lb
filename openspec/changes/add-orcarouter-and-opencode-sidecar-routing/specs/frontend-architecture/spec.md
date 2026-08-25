## ADDED Requirements

### Requirement: Expose OrcaRouter, OpenCode Zen, and OpenCode Free in external integrations tabs

Settings MUST expose OrcaRouter Integration, OpenCode Zen Integration, and OpenCode Free Integration tabs inside the existing "External Integrations" card. Each tab MUST include an enable toggle above the explanation callout, base URL, prefixes, full models, discovered models, timeouts, status, reasoning-effort override, and test-connection behavior.

The OrcaRouter tab MUST include an API key field. The OpenCode Zen tab MUST include an API key field. The OpenCode Free tab MUST NOT require an API key to enable, persist, discover models, or test the connection. The implementation MUST add `OrcaRouterSidecarSettings`, `OpenCodeZenSidecarSettings`, and `OpenCodeSidecarSettings` components accepting `bare?: boolean` and exactly one tab entry each in the existing `tabs` array in `sidecar-integrations.tsx`.

The implementation MUST NOT create new top-level Settings cards for these integrations and MUST NOT restructure the existing external integrations card, tab list, tab trigger, or tab content layout. Conflict detection MUST use the same cross-integration prefix and full-model checks as the existing sidecar integrations.

#### Scenario: All three providers appear as tabs

- **WHEN** an authenticated operator opens Settings
- **THEN** the "External Integrations" card includes tabs for CLIProxyAPI, OpenRouter, OmniRoute, Ollama, OrcaRouter, OpenCode Zen, and OpenCode Free
- **AND** selecting the OrcaRouter tab shows `OrcaRouter Integration`
- **AND** selecting the OpenCode Zen tab shows `OpenCode Zen Integration`
- **AND** selecting the OpenCode Free tab shows `OpenCode Free Integration`

#### Scenario: Enabled OrcaRouter can be the default active tab

- **GIVEN** only the OrcaRouter sidecar integration is enabled
- **WHEN** an authenticated operator opens Settings
- **THEN** the OrcaRouter tab is active by default

#### Scenario: Enabled OpenCode Zen can be the default active tab

- **GIVEN** only the OpenCode Zen sidecar integration is enabled
- **WHEN** an authenticated operator opens Settings
- **THEN** the OpenCode Zen tab is active by default

#### Scenario: Enabled OpenCode Free can be the default active tab

- **GIVEN** only the OpenCode Free sidecar integration is enabled
- **WHEN** an authenticated operator opens Settings
- **THEN** the OpenCode Free tab is active by default

#### Scenario: OpenCode Free test connection works without an API key

- **GIVEN** OpenCode Free is enabled and no API key is stored
- **WHEN** an authenticated operator tests the OpenCode Free connection
- **THEN** the dashboard performs the upstream check without requiring a key

#### Scenario: OpenCode Zen test connection requires an API key

- **GIVEN** OpenCode Zen is enabled and no API key is stored
- **WHEN** an authenticated operator tests the OpenCode Zen connection
- **THEN** the dashboard reports missing-key status
- **AND** the dashboard does not call the zen host

#### Scenario: Discovered OrcaRouter model can be added as full model

- **GIVEN** OrcaRouter model discovery returns `orcarouter/auto`
- **WHEN** an authenticated operator adds that discovered model from the OrcaRouter tab
- **THEN** the settings save payload includes `orcarouterSidecarFullModels` containing `orcarouter/auto`

#### Scenario: Discovered OpenCode Zen model can be added as full model

- **GIVEN** OpenCode Zen model discovery returns `mimo-v2.5-free`
- **WHEN** an authenticated operator adds that discovered model from the OpenCode Zen tab
- **THEN** the settings save payload includes an OpenCode Zen full-model entry for that model

#### Scenario: Discovered OpenCode Free model can be added as full model

- **GIVEN** OpenCode Free model discovery returns `big-pickle`
- **WHEN** an authenticated operator adds that discovered model from the OpenCode Free tab
- **THEN** the settings save payload includes an OpenCode Free full-model entry for that model

#### Scenario: Duplicate sidecar routes are rejected inline

- **GIVEN** OmniRoute already owns prefix `oc/`
- **WHEN** an authenticated operator tries to add prefix `oc/` in the OpenCode Free tab
- **THEN** the OpenCode Free tab shows an inline conflict
- **AND** the duplicate route is not persisted

#### Scenario: OmniRoute orcarouter prefix conflict is rejected inline

- **GIVEN** OmniRoute already owns prefix `orcarouter/`
- **WHEN** an authenticated operator tries to add prefix `orcarouter/` in the OrcaRouter tab
- **THEN** the OrcaRouter tab shows an inline conflict
- **AND** the duplicate route is not persisted

#### Scenario: OmniRoute opencode-zen prefix conflict is rejected inline

- **GIVEN** OmniRoute already owns prefix `opencode-zen/`
- **WHEN** an authenticated operator tries to add prefix `opencode-zen/` in the OpenCode Zen tab
- **THEN** the OpenCode Zen tab shows an inline conflict
- **AND** the duplicate route is not persisted
