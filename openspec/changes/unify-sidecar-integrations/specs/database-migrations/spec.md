## ADDED Requirements

### Requirement: Sidecar prefix and full-model schema migration preserves behavior

A single Alembic revision on the current head SHALL migrate sidecar settings to the unified shape and SHALL preserve current effective routing behavior. The upgrade SHALL convert each integration's stored prefix array of strings into an array of `{prefix, strip}` objects, setting `strip` true for prefixes ending in `-` or `_` and false otherwise. The upgrade SHALL ensure CLIProxyAPI and OpenRouter each have a stored full-model list (defaulting to empty) and SHALL preserve OmniRoute's existing selected models as its full-model list. The upgrade SHALL seed the CLIProxyAPI default prefix rows `cp-` and `cp_` with strip enabled where absent, reproducing the previously built-in alias behavior. The revision SHALL provide a downgrade that restores the prior string-array prefix shape and removes added full-model storage.

#### Scenario: Upgrade backfills strip flags from prefix suffix

- **GIVEN** an integration stored prefixes `["claude", "cp-"]`
- **WHEN** the migration upgrade runs
- **THEN** the stored prefixes become `[{prefix: "claude", strip: false}, {prefix: "cp-", strip: true}]`

#### Scenario: Upgrade seeds CLIProxyAPI alias prefixes with strip enabled

- **GIVEN** CLIProxyAPI prefixes do not include `cp-` or `cp_`
- **WHEN** the migration upgrade runs
- **THEN** `cp-` and `cp_` are added to CLIProxyAPI prefixes with strip enabled

#### Scenario: Upgrade preserves OmniRoute selected models as full models

- **GIVEN** OmniRoute selected models are `["minimax/minimax-m3"]`
- **WHEN** the migration upgrade runs
- **THEN** OmniRoute's full-model list contains `minimax/minimax-m3`

#### Scenario: Downgrade restores string-array prefixes

- **GIVEN** the upgrade has been applied
- **WHEN** the migration downgrade runs
- **THEN** each integration's prefixes are stored as a string array
- **AND** the added full-model storage is removed
```
