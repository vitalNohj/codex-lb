## ADDED Requirements

### Requirement: Dashboard navigation links to OmniRoute

The dashboard header SHALL expose an OmniRoute navigation action for authenticated operators. The action MUST open `/omni` on the current origin, and it MUST be rendered only inside the authenticated dashboard shell.

#### Scenario: Authenticated operator opens OmniRoute

- **WHEN** an authenticated operator views the codex-lb dashboard header
- **THEN** the header shows an OmniRoute navigation action
- **AND** activating the action opens `/omni` on the current origin

#### Scenario: Link is not rendered before dashboard authentication

- **WHEN** the dashboard is still blocked by authentication
- **THEN** the OmniRoute navigation action is not rendered
