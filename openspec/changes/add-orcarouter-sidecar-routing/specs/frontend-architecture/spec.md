## ADDED Requirements

### Requirement: Settings exposes an OrcaRouter External Integrations tab

The External Integrations card MUST add exactly one tab labeled `OrcaRouter` after OpenRouter. The tab MUST use the existing `SidecarIntegrationCard` autosave pattern. The enable toggle MUST render above the callout.

The tab MUST expose enable, base URL, API key, prefixes, full models, discovered models, timeouts, effort override, status, and test-on-save-key behavior. External links MUST use `target="_blank"` and `rel="noopener noreferrer"`.

The callout MUST tell operators that OmniRoute may already own `orcarouter/` and to remove that OmniRoute prefix before enabling.

`SidecarIntegrationId` MUST include `orcarouter`. Conflict collection MUST include OrcaRouter prefixes and full models.

#### Scenario: OrcaRouter tab is present and off by default

- **GIVEN** the operator opens Settings
- **WHEN** the External Integrations card renders
- **THEN** a tab labeled `OrcaRouter` is visible
- **AND** the enable switch is off by default

#### Scenario: Enable toggle is above the callout

- **GIVEN** the OrcaRouter tab is selected
- **WHEN** the integration form renders
- **THEN** the enable switch appears above the setup callout

### Requirement: Synthetic account UI has an explicit OrcaRouter branch

Account detail, list subtitle, effort override, and read-only actions MUST treat `provider === "orcarouter"` as OrcaRouter. That account MUST NOT inherit Claude pause or quota UI.

Claude-specific UI MUST be selected by an allowlist on `provider === "claude"`, not by excluding known non-Claude providers, so a provider added later cannot inherit Claude pause and quota controls by default. This applies to the dashboard card and list expanders as well as account detail.

#### Scenario: OrcaRouter synthetic account is not Claude

- **GIVEN** a synthetic account with `provider: "orcarouter"`
- **WHEN** the operator opens account detail
- **THEN** the heading/display is OrcaRouter
- **AND** Claude pause and quota controls are not shown

#### Scenario: A non-Claude synthetic with auth rows does not expand into Claude cards

- **GIVEN** a synthetic account with `provider: "orcarouter"` and a non-empty `sidecarAuths`
- **WHEN** the dashboard renders the account cards or the account list
- **THEN** the account renders as a single OrcaRouter entry
- **AND** no Claude per-auth pause controls are rendered
