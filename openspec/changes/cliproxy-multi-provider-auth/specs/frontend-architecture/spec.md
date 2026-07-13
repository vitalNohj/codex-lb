# frontend-architecture (delta)

## ADDED Requirements

### Requirement: Settings CLIProxyAPI routing UI lists all providers in one pool

The Settings CLIProxyAPI integration routing controls MUST list every ingested CLIProxyAPI auth account in one priority/pause table for the single global strategy, and MUST show a human-readable provider label on each row so interleaved Claude and Grok (and future) priorities remain understandable. The UI MUST NOT present a second strategy control per provider.

#### Scenario: Mixed-provider priority rows render

- **GIVEN** routing state includes a Claude auth and a Grok/xAI auth
- **WHEN** an operator opens the CLIProxyAPI integration routing section
- **THEN** both accounts appear in the same priority list
- **AND** each row shows account identity and provider label
- **AND** only one strategy dropdown is shown for the integration

#### Scenario: Pause from Settings works for non-Claude rows

- **GIVEN** a Grok/xAI auth row is visible in the CLIProxyAPI routing list
- **WHEN** an operator toggles Pause/Resume on that row
- **THEN** the existing CLIProxyAPI pause mutation is invoked for that auth-file identity
- **AND** the row updates to the new paused state

### Requirement: Dashboard CLIProxyAPI auth cards stay Codex-parity with adapter windows

The Dashboard MUST continue to render one card (and one list row) per CLIProxyAPI auth account with the Codex-parity chrome: header, provider-aware subtitle, quota widget, reasoning-effort override in the warm-up slot, Details, and Pause/Resume, without a credits row and without warm-up controls. The quota widget MUST render only the windows declared for that auth's provider adapter (weekly when available; five-hour only when available). When live windows are unavailable and manual estimation is supported, the Accounts/detail surfaces MUST expose Claude-style manual auth-plan / estimation inputs for that auth identity.

#### Scenario: Claude auth card still shows five-hour and weekly when available

- **GIVEN** a Claude CLIProxyAPI auth with live or estimated five-hour and weekly usage
- **WHEN** the Dashboard accounts card view renders
- **THEN** that auth renders as its own card
- **AND** five-hour and weekly quota bars are shown

#### Scenario: Grok auth card omits five-hour when adapter has weekly only

- **GIVEN** a Grok/xAI CLIProxyAPI auth whose adapter declares weekly only
- **WHEN** the Dashboard accounts card view renders
- **THEN** that auth renders as its own card with the same chrome family as Claude CLIProxyAPI cards
- **AND** a weekly quota bar is shown
- **AND** no live five-hour bar is shown for that card

#### Scenario: Manual estimation inputs available when live Grok limits are missing

- **GIVEN** a Grok/xAI CLIProxyAPI auth with no live usage windows
- **WHEN** an operator opens the Accounts detail / quota estimation surface for that auth
- **THEN** manual plan/estimation inputs are available in the same workflow shape used for Claude CLIProxyAPI estimation
- **AND** saving those inputs does not overwrite unrelated Claude auth plans

#### Scenario: Card subtitle names provider without changing Request Logs Account format

- **GIVEN** a Grok/xAI CLIProxyAPI auth card
- **WHEN** the card subtitle renders
- **THEN** the subtitle includes a Grok/xAI (or equivalent) provider label in the existing `<tier> | <provider>` pattern
- **AND** this subtitle contract does not change Request Logs Account cell formatting

### Requirement: Request Logs Account cells stay provider-agnostic for CLIProxyAPI

The Request Logs table MUST render CLIProxyAPI Account cells as `CLIProxyAPI: <account label>` when a sidecar account label is present and `CLIProxyAPI` otherwise, and MUST NOT insert Claude, Grok, xAI, or other upstream-provider qualifiers into that Account cell. The Model column remains the primary signal for which upstream family served the request.

#### Scenario: Grok row account cell

- **GIVEN** a request-log row sourced from the CLIProxyAPI sidecar with `sidecarAccountLabel="grok-user@example.com"`
- **WHEN** the Request Logs table renders the Account cell
- **THEN** the cell text is `CLIProxyAPI: grok-user@example.com`
- **AND** the cell text does not include `Grok` or `xAI`

#### Scenario: Claude row account cell shape unchanged

- **GIVEN** a request-log row sourced from the CLIProxyAPI sidecar with `sidecarAccountLabel="claude-user@example.com"`
- **WHEN** the Request Logs table renders the Account cell
- **THEN** the cell text is `CLIProxyAPI: claude-user@example.com`
- **AND** the cell text does not include `Claude`

#### Scenario: Missing account label

- **GIVEN** a CLIProxyAPI sidecar request-log row with no sidecar account label
- **WHEN** the Request Logs table renders the Account cell
- **THEN** the cell text is `CLIProxyAPI`
