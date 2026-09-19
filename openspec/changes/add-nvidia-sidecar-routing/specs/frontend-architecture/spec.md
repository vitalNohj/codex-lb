## ADDED Requirements

### Requirement: Settings exposes a NVIDIA External Integrations tab

The External Integrations card MUST add exactly one tab labeled `NVIDIA` after OpenRouter and before OrcaRouter. The tab MUST use the existing `SidecarIntegrationCard` autosave pattern. The enable toggle MUST render above the callout.

The tab MUST expose enable, base URL (prefilled to `https://integrate.api.nvidia.com/v1`), API key, prefixes, full models, discovered models, timeouts, effort override, status, and test-on-save-key behavior. External links MUST use `target="_blank"` and `rel="noopener noreferrer"`.

`SidecarIntegrationId` MUST include `nvidia`. Conflict collection MUST include NVIDIA prefixes and full models.

#### Scenario: NVIDIA tab is present and off by default

- **GIVEN** the operator opens Settings
- **WHEN** the External Integrations card renders
- **THEN** a tab labeled `NVIDIA` is visible
- **AND** the enable switch is off by default
- **AND** the base URL field is prefilled with `https://integrate.api.nvidia.com/v1`

#### Scenario: Enable toggle is above the callout

- **GIVEN** the NVIDIA tab is selected
- **WHEN** the integration form renders
- **THEN** the enable switch appears above the setup callout

#### Scenario: Discovered models can be pinned

- **GIVEN** NVIDIA is enabled with an API key
- **AND** the discovered-models list includes `z-ai/glm-5.3`
- **WHEN** the operator adds that id
- **THEN** the full-models list includes `z-ai/glm-5.3`

### Requirement: Synthetic account UI has an explicit NVIDIA branch

Account detail, list subtitle, effort override, and read-only actions MUST treat `provider === "nvidia"` as NVIDIA. That account MUST NOT inherit Claude pause or quota UI.

Claude-specific UI MUST be selected by an allowlist on the Claude provider, not by excluding known non-Claude providers. NVIDIA MUST match OpenRouter for generic sidecar status rows: hide `Quota` and `Models`.

#### Scenario: NVIDIA synthetic account is not Claude

- **GIVEN** a synthetic account with `provider: "nvidia"`
- **WHEN** the operator opens account detail
- **THEN** the heading/display is NVIDIA
- **AND** Claude pause and quota controls are not shown

#### Scenario: Generic sidecar status rows follow the aggregator rule

- **GIVEN** synthetic accounts for NVIDIA, OpenRouter, and Ollama
- **WHEN** the accounts list renders each item
- **THEN** the NVIDIA item hides `Quota` and `Models`, matching OpenRouter
- **AND** the Ollama item still renders `Quota` and `Models`

### Requirement: Dashboard account-type filter covers NVIDIA

The dashboard account-type visibility filter MUST expose an `nvidia` key, rendered after `OpenRouter` and before `OrcaRouter` to match `SIDECAR_PROVIDER_ORDER`. It MUST default to visible, including when hydrating a persisted preference written before the key existed, and MUST NOT reset the other stored toggles while filling it in.

#### Scenario: NVIDIA accounts have their own toggle

- **GIVEN** the dashboard renders a synthetic account with `provider: "nvidia"`
- **WHEN** the operator turns the `NVIDIA` account-type toggle off
- **THEN** that account is removed from the rendered accounts
- **AND** the other account types stay visible
