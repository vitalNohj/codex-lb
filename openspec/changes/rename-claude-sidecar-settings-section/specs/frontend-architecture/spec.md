## MODIFIED Requirements

### Requirement: Settings page

The Settings page SHALL include sections for: routing settings (sticky threads, reset priority, prompt-cache affinity TTL), password management (setup/change/remove), TOTP management (setup/disable), API key auth toggle, API key management (table, create, edit, delete, regenerate), sticky-session administration, and sidecar integration settings. The Claude CLIProxyAPI sidecar settings section MUST render its visible heading as `CLIProxyAPI Integration`. The OpenRouter sidecar settings section MUST render its visible heading as `OpenRouter Integration`. The OmniRoute sidecar settings section MUST render its visible heading as `OmniRoute Integration`.

#### Scenario: Claude sidecar settings heading uses CLIProxyAPI language

- **WHEN** a user opens the Settings page
- **THEN** the Claude CLIProxyAPI sidecar settings section heading is `CLIProxyAPI Integration`

#### Scenario: OpenRouter sidecar settings heading uses integration language

- **WHEN** a user opens the Settings page
- **THEN** the OpenRouter sidecar settings section heading is `OpenRouter Integration`

#### Scenario: OmniRoute sidecar settings heading uses integration language

- **WHEN** a user opens the Settings page
- **THEN** the OmniRoute sidecar settings section heading is `OmniRoute Integration`

#### Scenario: Save prompt-cache affinity TTL
- **WHEN** a user updates the prompt-cache affinity TTL from the routing settings section
- **THEN** the app calls `PUT /api/settings` with the updated TTL and reflects the saved value

#### Scenario: View sticky-session mappings
- **WHEN** a user opens the sticky-session section on the Settings page
- **THEN** the app fetches sticky-session entries and displays each mapping's kind, account, timestamps, and stale/expiry state

#### Scenario: Purge stale prompt-cache mappings
- **WHEN** a user requests a stale purge from the sticky-session section
- **THEN** the app calls the sticky-session purge API and refreshes the list afterward
