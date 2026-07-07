## MODIFIED Requirements

### Requirement: CLI Proxy API synthetic card presentation

The dashboard card view MUST render each CLI Proxy API (Claude sidecar) auth account in `sidecarAuths` as its own account card that mirrors the native Codex account-card layout. Each CLI Proxy API auth card MUST render a header with the auth account's email (or, when no email exists, its name) as the title, a subtitle combining the auth plan label and the credential provider label, and a status badge. The credential provider label MUST be `Claude` when the auth account's provider is known to be Claude, and MUST fall back to `CLIProxyAPI` when the provider cannot be determined. Each card MUST render that auth account's 5h and weekly remaining quota bars. Each card MUST render the per-provider reasoning-effort override in the slot where native cards render warm-up controls. Each card MUST render a `Details` action and a `Pause`/`Resume` action, where the pause action toggles that auth account's paused state.

CLI Proxy API auth cards MUST NOT render a credits row, warm-up controls, or the `Health`, `Quota`, `Models`, or `Requests` metadata rows. The auth account title MUST be hideable via dashboard privacy mode using the same blur treatment as regular account emails.

When the Claude sidecar has no sidecar auth accounts but still has aggregate usage data, the dashboard MUST render a single fallback card headed `Claude Usage`.

#### Scenario: Each CLI Proxy API auth renders a codex-style card

- **WHEN** the dashboard card view renders a Claude sidecar synthetic account with one or more sidecar auth accounts
- **THEN** each sidecar auth account renders its own account card titled by its email (or name)
- **AND** each card renders 5h and weekly quota bars
- **AND** each card renders a `Details` action and a `Pause` or `Resume` action
- **AND** each card does not render a credits row, warm-up controls, or the `Health`, `Quota`, `Models`, or `Requests` metadata rows

#### Scenario: Auth card subtitle labels the credential provider

- **WHEN** a CLI Proxy API auth card renders for an auth account whose provider is known to be Claude
- **THEN** the card subtitle includes `Claude` as the provider label

#### Scenario: Auth card subtitle falls back when provider is unknown

- **WHEN** a CLI Proxy API auth card renders for an auth account whose provider cannot be determined
- **THEN** the card subtitle includes `CLIProxyAPI` as the provider label

#### Scenario: CLI Proxy API auth card pause toggles the auth account

- **WHEN** an operator activates the `Pause` action on an unpaused CLI Proxy API auth card
- **THEN** that auth account's paused state is toggled through the Claude sidecar account pause endpoint

#### Scenario: Paused CLI Proxy API auth card shows Resume

- **WHEN** the dashboard card view renders a paused CLI Proxy API auth account
- **THEN** the card renders a `Resume` action instead of `Pause`

#### Scenario: CLI Proxy API auth card title respects privacy mode

- **WHEN** dashboard privacy mode is enabled and a CLI Proxy API auth card renders
- **THEN** the auth email or name in the card title is blurred

### Requirement: CLI Proxy API synthetic list-row presentation

The dashboard list (tiered) view MUST render each CLI Proxy API (Claude sidecar) auth account in `sidecarAuths` as its own list row that mirrors the native account list row layout. Each CLI Proxy API auth row MUST render the auth account's email (or, when no email exists, its name) as the account label with the credential provider label as its subtitle, a status badge, the auth plan label in the plan column, and that auth account's 5h and weekly remaining quota bars in the quota column. Each row MUST render the per-provider reasoning-effort override in the warm-up column and a placeholder (`-`) in the credits column. Each row MUST render a `Details` action and a `Pause`/`Resume` action, where the pause action toggles that auth account's paused state. The auth account label MUST be hideable via dashboard privacy mode using the same blur treatment as regular account rows.

#### Scenario: Each CLI Proxy API auth renders its own list row

- **WHEN** the dashboard list view renders a Claude sidecar synthetic account with one or more sidecar auth accounts
- **THEN** each sidecar auth account renders its own list row labeled by its email (or name)
- **AND** each row renders 5h and weekly quota bars
- **AND** each row renders a `Details` action and a `Pause` or `Resume` action

#### Scenario: CLI Proxy API auth row pause toggles the auth account

- **WHEN** an operator activates the `Pause` action on an unpaused CLI Proxy API auth list row
- **THEN** that auth account's paused state is toggled through the Claude sidecar account pause endpoint

#### Scenario: Paused CLI Proxy API auth row shows Resume

- **WHEN** the dashboard list view renders a paused CLI Proxy API auth account
- **THEN** the row renders a `Resume` action instead of `Pause`
