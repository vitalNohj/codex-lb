## MODIFIED Requirements

### Requirement: Dashboard navigation links to OmniRoute

The dashboard header SHALL expose an OmniRoute navigation action for authenticated operators. The action MUST open `/omni` on the current origin, MUST open in a new browser tab by default, MUST set `rel="noopener noreferrer"`, and MUST be rendered only inside the authenticated dashboard shell. The OmniRoute sidecar settings card MUST also expose an "Open OmniRoute" action that opens `/omni` in a new browser tab by default and sets `rel="noopener noreferrer"`.

#### Scenario: Authenticated operator opens OmniRoute from the header

- **WHEN** an authenticated operator views the codex-lb dashboard header
- **THEN** the header shows an OmniRoute navigation action
- **AND** activating the action opens `/omni` on the current origin in a new browser tab
- **AND** the action prevents the new tab from accessing the opener window

#### Scenario: Authenticated operator opens OmniRoute from settings

- **WHEN** an authenticated operator views the OmniRoute sidecar settings card
- **THEN** the card shows an "Open OmniRoute" action
- **AND** activating the action opens `/omni` on the current origin in a new browser tab
- **AND** the action prevents the new tab from accessing the opener window

#### Scenario: Link is not rendered before dashboard authentication

- **WHEN** the dashboard is still blocked by authentication
- **THEN** the OmniRoute navigation action is not rendered
