# frontend-architecture (delta)

## ADDED Requirements

### Requirement: Settings CLIProxyAPI routing UI lists all providers in one labeled pool

The Settings CLIProxyAPI routing controls MUST list every ingested CLIProxyAPI auth account in one priority/pause table for the single global strategy, and MUST show a human-readable provider label derived from each account's normalized `provider` on every row. The UI MUST NOT present a second strategy control per provider, and empty-state copy MUST NOT claim that only Claude accounts are supported when multi-provider ingestion is active.

#### Scenario: Mixed-provider priority rows render with provider labels

- **GIVEN** routing state includes a Claude auth and a Grok/xAI auth
- **WHEN** an operator opens the CLIProxyAPI routing section
- **THEN** both accounts appear in the same priority list
- **AND** each row shows account identity and provider label
- **AND** only one strategy dropdown is shown

#### Scenario: Pause works for non-Claude rows

- **GIVEN** a Grok/xAI auth row is visible
- **WHEN** an operator toggles Pause/Resume on that row
- **THEN** the existing CLIProxyAPI pause mutation runs for that auth-file identity
- **AND** the row reflects the new paused state

### Requirement: Dashboard CLIProxyAPI auth cards render only declared quota windows

Dashboard CLIProxyAPI per-auth cards and list rows MUST keep Codex-parity chrome (header, `<tier> | <provider>` subtitle, effort override in the warm-up slot, Details, Pause/Resume; no credits; no warm-up controls) and MUST render quota bars only for windows present in that auth's `quota_windows`. A weekly-only auth MUST NOT show a five-hour bar. When `supports_manual_plan` is true and live windows are empty, Accounts estimation surfaces MUST expose manual plan inputs without defaulting non-Claude auths to Claude `pro`/`max*` presets.

#### Scenario: Claude auth still shows five-hour and weekly when declared

- **GIVEN** a Claude auth with `quota_windows` containing `five_hour` and `weekly`
- **WHEN** the Dashboard card view renders
- **THEN** five-hour and weekly bars are shown on that auth card

#### Scenario: Grok auth hides five-hour when not declared

- **GIVEN** a Grok/xAI auth whose `quota_windows` is `["weekly"]` or empty
- **WHEN** the Dashboard card or list row renders
- **THEN** no five-hour bar is shown for that auth
- **AND** a weekly bar is shown only when `weekly` is present in `quota_windows` or supplied by a manual estimate for that window

#### Scenario: Manual estimation available for non-Claude without Claude presets

- **GIVEN** a Grok/xAI auth with `supports_manual_plan=true`
- **WHEN** an operator opens Accounts quota estimation for that auth
- **THEN** manual plan inputs are available
- **AND** the UI does not preselect Claude `pro`/`max5`/`max20` as the default plan type for that Grok auth
- **AND** saving the Grok plan does not overwrite unrelated Claude plans

#### Scenario: Card subtitle may name provider without changing Request Logs Account format

- **GIVEN** a Grok/xAI auth card
- **WHEN** the subtitle renders
- **THEN** the subtitle uses the existing `<tier> | <provider>` pattern with a Grok/xAI (or equivalent) provider label
- **AND** Request Logs Account cells remain `CLIProxyAPI: <account>` without a provider qualifier

### Requirement: Request Logs Account cells stay provider-agnostic for CLIProxyAPI

The Request Logs table MUST render CLIProxyAPI Account cells as `CLIProxyAPI: <account label>` when a sidecar account label is present and `CLIProxyAPI` otherwise, and MUST NOT insert Claude, Grok, xAI, or other upstream-provider qualifiers into that Account cell.

#### Scenario: Grok row account cell

- **GIVEN** a CLIProxyAPI sidecar request-log row with `sidecarAccountLabel="grok-user@example.com"`
- **WHEN** the Account cell renders
- **THEN** the text is `CLIProxyAPI: grok-user@example.com`
- **AND** the text does not include `Grok` or `xAI`

#### Scenario: Claude row account cell shape unchanged

- **GIVEN** a CLIProxyAPI sidecar request-log row with `sidecarAccountLabel="claude-user@example.com"`
- **WHEN** the Account cell renders
- **THEN** the text is `CLIProxyAPI: claude-user@example.com`
- **AND** the text does not include `Claude`

#### Scenario: Missing account label

- **GIVEN** a CLIProxyAPI sidecar request-log row with no sidecar account label
- **WHEN** the Account cell renders
- **THEN** the text is `CLIProxyAPI`

### Requirement: Remove Claude-only operator copy from CLIProxyAPI surfaces that become multi-provider

Settings and Accounts copy for the CLIProxyAPI integration MUST NOT state that the integration only supports Claude accounts or only Claude login once multi-provider auth ingestion is active. The External Integrations tab name remains `CLIProxyAPI`. Shared effort-override help MAY note that one override applies to all CLIProxyAPI upstreams.

#### Scenario: Routing empty state is provider-neutral

- **GIVEN** multi-provider ingestion is active and no auth files are returned
- **WHEN** the routing list empty state renders
- **THEN** the copy does not say “No Claude accounts” as if Claude were the only supported provider

#### Scenario: Settings explanation mentions multi-upstream auth

- **GIVEN** the CLIProxyAPI settings card is open
- **WHEN** the explanation/help text renders
- **THEN** it does not claim Claude is the only supported CLIProxyAPI upstream
- **AND** it may still document `cli-proxy-api --claude-login` and `--xai-login` as operator setup steps
