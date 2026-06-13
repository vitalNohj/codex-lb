## MODIFIED Requirements

### Requirement: Account card row height is 14rem

The dashboard account card viewport MUST use 14rem per visible row so at least two full rows of account cards are visible before the grid scrolls.

#### Scenario: Account card max height

- **WHEN** the account cards container renders with `ACCOUNT_CARD_VISIBLE_ROWS=2`
- **THEN** the container `maxHeight` is `calc(2 * 14rem + 1rem)`

## ADDED Requirements

### Requirement: CLI Proxy API synthetic card presentation

The dashboard MUST render the Claude sidecar synthetic account card with the title `CLI Proxy API`. The card MUST render one usage panel per sidecar auth account in `sidecarAuths`, and each usage panel MUST be headed by that auth account's email (or, when no email exists, its name) followed by `Usage`. Each per-auth usage panel MUST show that auth account's 5h and weekly remaining quota. The auth account email or name in each panel heading MUST be hideable via dashboard privacy mode using the same blur treatment as regular account emails. The Claude synthetic card MUST NOT render the `Health`, `Quota`, `Models`, or `Requests` metadata rows.

When the Claude sidecar has no sidecar auth accounts but still has aggregate usage data, the card MUST render a single fallback usage panel headed `Claude Usage`.

#### Scenario: Claude synthetic card shows per-auth usage and CLI Proxy API title

- **WHEN** the Claude sidecar synthetic account card renders with one or more sidecar auth accounts
- **THEN** the card title is `CLI Proxy API`
- **AND** each sidecar auth account renders a usage panel headed by its email (or name) plus `Usage`
- **AND** the card does not render the `Health`, `Quota`, `Models`, or `Requests` metadata rows

#### Scenario: Claude synthetic card auth label respects privacy mode

- **WHEN** dashboard privacy mode is enabled and the Claude synthetic card renders an auth usage panel
- **THEN** the auth email or name in the panel heading is blurred

### Requirement: Enabled sidecar synthetic accounts are active

The OpenRouter and OmniRoute synthetic account summaries MUST report `status` of `active` when the corresponding sidecar is enabled and an API key is configured. When the sidecar is disabled or missing an API key, the summary MUST report `status` of `paused`. The synthetic account `health_status` MUST continue to reflect the latest health probe state independently of the account status.

#### Scenario: Enabled and configured OpenRouter sidecar is active

- **WHEN** the OpenRouter sidecar is enabled and an API key is configured
- **THEN** the OpenRouter synthetic account summary `status` is `active`

#### Scenario: Disabled OmniRoute sidecar is paused

- **WHEN** the OmniRoute sidecar is disabled
- **THEN** the OmniRoute synthetic account summary `status` is `paused`
