## ADDED Requirements

### Requirement: Settings exposes an OrcaRouter External Integrations tab

The External Integrations card MUST add exactly one tab labeled `OrcaRouter` after OpenRouter. The tab MUST use the existing `SidecarIntegrationCard` autosave pattern. The enable toggle MUST render above the callout.

The tab MUST expose enable, base URL, API key, prefixes, full models, discovered models, timeouts, effort override, status, and test-on-save-key behavior. External links MUST use `target="_blank"` and `rel="noopener noreferrer"`.

The callout MUST tell operators that OmniRoute may already own `orcarouter/` and to remove that OmniRoute prefix before enabling.

`SidecarIntegrationId` MUST include `orcarouter`. Conflict collection MUST include OrcaRouter prefixes and full models.

#### Scenario: OrcaRouter tab is present and off by default

- **GIVEN** the operator opens Settings
- **WHEN** the External Integrations card renders
- **THEN** a tab labeled `OrcaRouter` is visible
- **AND** the enable switch is off by default

#### Scenario: Enable toggle is above the callout

- **GIVEN** the OrcaRouter tab is selected
- **WHEN** the integration form renders
- **THEN** the enable switch appears above the setup callout

### Requirement: Synthetic account UI has an explicit OrcaRouter branch

Account detail, list subtitle, effort override, and read-only actions MUST treat `provider === "orcarouter"` as OrcaRouter. That account MUST NOT inherit Claude pause or quota UI.

Claude-specific UI MUST be selected by an allowlist on the Claude provider, not by excluding known non-Claude providers, so a provider added later cannot inherit Claude pause and quota controls by default. Because the account schema declares `provider` as nullable/optional and the surrounding subtitle and connection-test fallbacks already resolve an absent provider to Claude, the allowlist MUST match `(provider ?? "claude") === "claude"` rather than `provider === "claude"`, so a Claude sidecar summary without a provider still renders its per-auth cards, quota block, and pause controls. This applies to the dashboard card and list expanders as well as account detail.

The accounts list item's generic sidecar status rows (`Quota`, `Models`) are NOT Claude-specific UI and MUST NOT be folded into that allowlist. They MUST stay hidden for the hosted aggregators (OpenRouter, OrcaRouter, OmniRoute), so OrcaRouter matches OpenRouter exactly, and MUST remain visible for the other synthetic providers. Only the 5h and Weekly subscription-window bars follow the Claude allowlist above.

#### Scenario: OrcaRouter synthetic account is not Claude

- **GIVEN** a synthetic account with `provider: "orcarouter"`
- **WHEN** the operator opens account detail
- **THEN** the heading/display is OrcaRouter
- **AND** Claude pause and quota controls are not shown

#### Scenario: A non-Claude synthetic with auth rows does not expand into Claude cards

- **GIVEN** a synthetic account with `provider: "orcarouter"` and a non-empty `sidecarAuths`
- **WHEN** the dashboard renders the account cards or the account list
- **THEN** the account renders as a single OrcaRouter entry
- **AND** no Claude per-auth pause controls are rendered

#### Scenario: Generic sidecar status rows follow the aggregator rule, not the Claude allowlist

- **GIVEN** synthetic accounts for OrcaRouter, OpenRouter, and Ollama
- **WHEN** the accounts list renders each item
- **THEN** the OrcaRouter item hides `Quota` and `Models`, matching OpenRouter
- **AND** the Ollama item still renders `Quota` and `Models`
- **AND** none of the three render the 5h or Weekly subscription bars

#### Scenario: Claude synthetic without a provider keeps its Claude UI

- **GIVEN** a synthetic account with a non-empty `sidecarAuths` and no `provider`
- **WHEN** the dashboard renders the account cards, the account list, or account detail
- **THEN** the account expands into its per-auth Claude cards with pause controls

### Requirement: Dashboard account-type filter covers OrcaRouter

The dashboard account-type visibility filter MUST expose an `orcarouter` key, rendered after `OpenRouter` and before `Omniroute` to match `SIDECAR_PROVIDER_ORDER`. It MUST default to visible, including when hydrating a persisted preference written before the key existed, and MUST NOT reset the other stored toggles while filling it in.

Account-type classification MUST resolve an absent provider to the CLIProxy key, for the same reason the Claude UI allowlist does. Unclassified accounts fall through to `other`, and accounts keyed `other` bypass the visibility filter entirely, so a Claude sidecar summary without a provider would otherwise be permanently visible.

#### Scenario: OrcaRouter accounts have their own toggle

- **GIVEN** the dashboard renders a synthetic account with `provider: "orcarouter"`
- **WHEN** the operator turns the `OrcaRouter` account-type toggle off
- **THEN** that account is removed from the rendered accounts
- **AND** the other account types stay visible

#### Scenario: Claude synthetic without a provider obeys the CLIProxy toggle

- **GIVEN** the dashboard renders a synthetic account with `sidecarAuths` and no `provider`
- **WHEN** the operator turns the `CLIProxy` account-type toggle off
- **THEN** that account is removed from the rendered accounts
