## ADDED Requirements

### Requirement: External integrations settings card

The Settings page MUST present the external integration settings (CLIProxyAPI, OpenRouter, OmniRoute) inside a single card titled "External Integrations" with a tab per integration, instead of separate stacked cards. The card MUST default to the first enabled integration's tab on load, falling back to the first tab when none are enabled. Each tab MUST indicate whether its integration is currently enabled in an accessible way. Selecting a tab MUST show that integration's existing configuration UI with its existing save, conflict-detection, and model-discovery behavior unchanged.

#### Scenario: Card opens on the first enabled integration

- **WHEN** an authenticated operator opens the Settings page and only one external integration is enabled
- **THEN** the "External Integrations" card is shown with one tab per integration
- **AND** the tab for the enabled integration is active by default
- **AND** the active tab shows that integration's configuration UI

#### Scenario: Card falls back to the first tab when none are enabled

- **WHEN** an authenticated operator opens the Settings page and no external integration is enabled
- **THEN** the first integration tab is active by default

#### Scenario: Switching tabs shows another integration

- **WHEN** an authenticated operator selects a different integration tab
- **THEN** that integration's configuration UI is shown
- **AND** its save and conflict-detection behavior is unchanged from the standalone card

#### Scenario: Tabs indicate enabled integrations

- **WHEN** an authenticated operator views the "External Integrations" card
- **THEN** each tab whose integration is enabled exposes an accessible enabled indicator
