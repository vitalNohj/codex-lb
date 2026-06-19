## ADDED Requirements

### Requirement: Sidecar integration settings persist edits without a Save button

The Settings page sidecar integration sections (CLIProxyAPI, OpenRouter, OmniRoute) MUST persist configuration edits through the settings update endpoint as the operator performs each action, and MUST NOT render a `Save` button. Adding or removing a prefix, toggling a prefix's strip checkbox, and adding or removing a full model (including selecting a discovered model) MUST persist immediately. The base URL and the timeout and model cache TTL fields MUST persist when the field loses focus or the operator presses Enter. Toggling the integration Enable switch MUST persist immediately. After a successful configuration persistence the matching provider connection test MUST run automatically; toggling the Enable switch MUST NOT trigger an automatic connection test.

#### Scenario: No Save button is rendered

- **WHEN** a sidecar integration section renders
- **THEN** it does not render a `Save` button

#### Scenario: Adding a prefix persists immediately

- **WHEN** an operator adds a prefix to a sidecar integration
- **THEN** the integration's prefix list is persisted through the settings update endpoint without any further action

#### Scenario: Editing the base URL persists on blur

- **WHEN** an operator edits the base URL field and the field loses focus or the operator presses Enter
- **THEN** the integration's base URL is persisted through the settings update endpoint

#### Scenario: Enable toggle persists without an auto-test

- **WHEN** an operator toggles a sidecar integration Enable switch
- **THEN** the enabled flag is persisted through the settings update endpoint
- **AND** the matching provider connection test does not run automatically

#### Scenario: Configuration persistence triggers an automatic test

- **WHEN** an operator's configuration edit persists successfully
- **THEN** the matching provider connection test runs automatically

### Requirement: Sidecar integration secrets use an explicit Add key control

The Settings page sidecar integration sections MUST manage stored API keys through an explicit `Add key` action next to the API key input, and the CLIProxyAPI section MUST also provide an explicit `Add management key` action next to the management key input. Activating an `Add key` action MUST persist the entered secret through the settings update endpoint, overwriting any previously stored secret of the same kind, and MUST clear the input afterward. The sidecar integration sections MUST NOT render a `Clear API key` button or a `Clear management key` button.

#### Scenario: Add API key overwrites the stored key

- **GIVEN** a sidecar integration already has a configured API key
- **WHEN** the operator enters a new API key and activates the `Add API key` action
- **THEN** the new API key is persisted through the settings update endpoint
- **AND** the input is cleared afterward

#### Scenario: CLIProxyAPI exposes an Add management key control

- **WHEN** the CLIProxyAPI integration section renders
- **THEN** it provides an `Add management key` action next to the management key input

#### Scenario: Clear key buttons are not rendered

- **WHEN** a sidecar integration section renders
- **THEN** it does not render a `Clear API key` button
- **AND** it does not render a `Clear management key` button
