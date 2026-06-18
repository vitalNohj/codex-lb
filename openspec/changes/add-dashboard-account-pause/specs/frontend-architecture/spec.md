## ADDED Requirements

### Requirement: Dashboard account card pause and resume controls

The Dashboard Accounts section account cards SHALL expose a direct `Pause`
action for normal (non-synthetic) Codex accounts that are pausable, so an
operator can pause an account without opening the account detail page. A
pausable account is a non-synthetic account whose status is not `paused`,
`reauth_required`, or `deactivated`. When an account status is `paused`, the
card SHALL expose the existing `Resume` action instead of `Pause`. The pause and
resume actions SHALL use the existing account pause/reactivate API path so the
account status and dashboard summaries refresh through the existing query
invalidation.

Synthetic, read-only sidecar account cards (CLIProxyAPI, OpenRouter, OmniRoute)
SHALL NOT expose pause or resume controls.

#### Scenario: Pause a normal active account from the dashboard

- **WHEN** a normal Codex account card renders with a non-paused, non-recovery status
- **THEN** the card shows a `Pause` action
- **AND** activating it dispatches the pause account action for that account
- **AND** the dashboard refreshes the account so its status reflects `paused`

#### Scenario: Paused account shows resume instead of pause

- **WHEN** a normal Codex account card renders with status `paused`
- **THEN** the card shows the `Resume` action
- **AND** the card does not show the `Pause` action

#### Scenario: Sidecar cards do not expose pause

- **WHEN** a synthetic, read-only sidecar account card renders for CLIProxyAPI, OpenRouter, or OmniRoute
- **THEN** the card does not show a `Pause` or `Resume` action
