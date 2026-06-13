## ADDED Requirements

### Requirement: Synthetic integration accounts omit duplicate provider badges

The Accounts page MUST NOT render a sidecar-type badge on synthetic integration account list items or synthetic integration account detail headers, because the account title already names the provider (`CLIProxyAPI`, `OpenRouter`, or `OmniRoute`). The account status badge MUST still render. OpenRouter and OmniRoute synthetic list items MUST NOT render a model-count row.

#### Scenario: Synthetic list item hides provider badge

- **WHEN** the Accounts list renders an OpenRouter or OmniRoute synthetic integration account
- **THEN** the list item does not render a duplicate provider-type badge
- **AND** the list item does not render a model-count row
- **AND** the account status badge still renders

#### Scenario: Synthetic detail header hides provider badge

- **WHEN** the Accounts detail panel renders a synthetic integration account
- **THEN** the detail header does not render a duplicate provider-type badge

### Requirement: Synthetic integration accounts surface connection status and manual test

The Accounts detail panel for a synthetic integration account (CLIProxyAPI, OpenRouter, OmniRoute) MUST display the integration connection status, including the connection state, configured base URL, last checked time when available, and the latest health message when present. The panel MUST provide a manual `Test connection` action wired to the matching provider test endpoint. The action MUST be disabled while a test is in flight, and the displayed connection status MUST refresh after the test settles, including when the test fails.

#### Scenario: Synthetic detail shows connection status

- **WHEN** the Accounts detail panel renders a synthetic integration account
- **THEN** the panel shows the integration connection state and configured base URL

#### Scenario: Manual test connection from Accounts

- **WHEN** a user clicks `Test connection` on a synthetic integration account detail panel
- **THEN** the dashboard calls the matching provider test endpoint
- **AND** the button is disabled while the test is in flight
- **AND** the displayed connection status refreshes after the test settles

### Requirement: CLIProxyAPI quota estimation lives in the Accounts tab

The CLIProxyAPI synthetic integration account detail panel MUST provide the quota estimation editor, allowing an operator to select a plan and token per discovered CLIProxyAPI auth and save the estimations. The OpenRouter and OmniRoute synthetic integration account detail panels MUST NOT render quota estimation controls. The Settings page MUST NOT render the CLIProxyAPI quota estimation editor.

#### Scenario: CLIProxyAPI quota editing in Accounts

- **WHEN** the Accounts detail panel renders the CLIProxyAPI synthetic integration account with one or more discovered auths
- **THEN** the panel renders the quota estimation editor with plan and token selection per auth
- **AND** saving persists the selected plans through the settings update endpoint

#### Scenario: OpenRouter and OmniRoute omit quota editing

- **WHEN** the Accounts detail panel renders the OpenRouter or OmniRoute synthetic integration account
- **THEN** the panel does not render quota estimation controls

### Requirement: Settings integration save runs connection test

Each Settings integration section (CLIProxyAPI, OpenRouter, OmniRoute) MUST NOT render a manual `Test connection` button. When an operator saves an integration's configuration, the Settings page MUST persist the configuration first and then automatically run the matching provider connection test. Toggling the integration Enable switch or clearing the stored API key MUST NOT trigger an automatic connection test.

#### Scenario: Save triggers automatic test

- **WHEN** an operator saves a CLIProxyAPI, OpenRouter, or OmniRoute integration configuration
- **THEN** the configuration persists first
- **AND** the matching provider connection test runs automatically after the save succeeds

#### Scenario: Enable toggle does not auto-test

- **WHEN** an operator toggles an integration Enable switch
- **THEN** the Settings page does not automatically run a connection test

#### Scenario: Settings integration section omits manual test button

- **WHEN** a Settings integration section renders
- **THEN** it does not render a `Test connection` button
