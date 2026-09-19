## ADDED Requirements

### Requirement: Settings exposes a plus control that creates named OpenAI-compat tabs

The External Integrations card MUST offer a `+` control on the tab row that is not itself a tab. Activating it MUST open a dialog that requires Name and Base URL. Confirming MUST append an endpoint to `openaiCompatEndpoints` and select the new tab.

Created tabs MUST render after the first-class integration tabs, in list order. Each tab MUST use the existing `SidecarIntegrationCard` autosave pattern. The enable toggle MUST render above the callout. Each tab MUST expose enable, base URL, optional API key, prefixes, full models, discovered models, timeouts, effort override, status, test-on-save-key, and Remove.

Conflict collection MUST include every generic endpoint's prefixes and full models. External links MUST use `target="_blank"` and `rel="noopener noreferrer"` when present.

#### Scenario: Plus creates a Vast tab

- **GIVEN** the operator opens Settings with no generic endpoints
- **WHEN** the operator uses `+` and submits name `Vast` and base URL `https://openai.vast.ai/my-endpoint/v1`
- **THEN** a tab labeled `Vast` is visible after the first-class tabs
- **AND** the enable switch is off by default
- **AND** the base URL field shows `https://openai.vast.ai/my-endpoint/v1`

#### Scenario: Enable toggle is above the callout

- **GIVEN** a generic endpoint tab is selected
- **WHEN** the integration form renders
- **THEN** the enable switch appears above the setup callout

#### Scenario: Remove deletes the tab

- **GIVEN** a generic endpoint tab exists
- **WHEN** the operator removes it
- **THEN** that tab is gone
- **AND** `openaiCompatEndpoints` no longer includes that id

### Requirement: Synthetic account UI has an explicit openai_compat branch

Account detail, list subtitle, effort override, and read-only actions MUST treat `provider === "openai_compat"` as a generic OpenAI-compat account. That account MUST NOT inherit Claude pause or quota UI. Quota and Models status rows MUST stay hidden, matching OpenRouter and NVIDIA.

Effort override on that account MUST write `defaultReasoningEffort` on the matching `openaiCompatEndpoints` item.

#### Scenario: Generic synthetic account is not Claude

- **GIVEN** a synthetic account with `provider: "openai_compat"` and display name `Vast`
- **WHEN** the operator opens account detail
- **THEN** the heading/display is Vast
- **AND** Claude pause and quota controls are not shown

### Requirement: Dashboard account-type filter covers generic OpenAI-compat accounts

The dashboard account-type visibility filter MUST expose an `openai_compat` key after the existing keys. It MUST default to visible, including when hydrating a persisted preference written before the key existed, and MUST NOT reset the other stored toggles while filling it in.

#### Scenario: Generic accounts have their own toggle

- **GIVEN** the dashboard renders a synthetic account with `provider: "openai_compat"`
- **WHEN** the operator turns the OpenAI-compat account-type toggle off
- **THEN** that account is removed from the rendered accounts
- **AND** the other account types stay visible
