## ADDED Requirements

### Requirement: Sidecar provider effort override is editable from Settings and account cards

The Settings page sidecar integration cards and the Accounts/Dashboard synthetic account cards SHALL expose the same per-provider reasoning effort override value and both SHALL persist changes through the settings update endpoint. Each sidecar provider (CLIProxyAPI/Claude, OpenRouter, OmniRoute, Ollama) renders a dropdown labeled `Reasoning effort override` with options `Default`, `None`, `Minimal`, `Low`, `Medium`, `High`, and `Extra high`, where `Default` corresponds to a null stored value and `Extra high` corresponds to `xhigh`. The Settings dropdown and the matching account-card dropdown MUST read and write the same settings field for that provider, so editing one reflects in the other after settings reload.

#### Scenario: Settings dropdown saves the selected effort

- **WHEN** an operator selects `Extra high` in a provider's Settings effort dropdown
- **THEN** the provider's default reasoning effort is persisted as `xhigh` through the settings update endpoint

#### Scenario: Settings dropdown can clear the effort

- **WHEN** an operator selects `Default` in a provider's Settings effort dropdown
- **THEN** the provider's default reasoning effort is persisted as null through the settings update endpoint

#### Scenario: Account card dropdown saves the same field

- **WHEN** an operator changes the effort dropdown on a provider's synthetic account card
- **THEN** the same provider default reasoning effort field is persisted through the settings update endpoint

#### Scenario: Account card reflects the stored effort

- **GIVEN** a provider's stored default reasoning effort is `xhigh`
- **WHEN** the provider's synthetic account card renders
- **THEN** the card's effort dropdown shows `Extra high`
