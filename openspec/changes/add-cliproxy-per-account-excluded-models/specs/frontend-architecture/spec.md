# frontend-architecture (delta)

## ADDED Requirements

### Requirement: CLIProxyAPI excluded-models editor

The dashboard MUST provide an excluded-models editor for each CLIProxyAPI Claude account that lets an operator both add and remove model exclusions. The editor MUST render a switch per well-known model family, a removable chip per pattern not represented by a family switch, and a free-text input for adding an arbitrary pattern. The editor MUST save every toggle, add, and removal immediately through the Claude sidecar excluded-models endpoint, sending the account's full resulting list, and MUST NOT require a separate Save button. The family-to-pattern map MUST live in frontend constants only, and the editor MUST send CLIProxyAPI wire model ids rather than `cc/`-prefixed alias ids.

#### Scenario: A family switch reflects an existing exclusion

- **WHEN** the editor renders for an account whose exclusion list contains a pattern belonging to a known model family
- **THEN** that family's switch renders as on

#### Scenario: Turning a family switch on excludes its patterns

- **WHEN** an operator turns on a family switch for an account with an empty exclusion list
- **THEN** the dashboard saves that account's exclusion list containing that family's pattern

#### Scenario: Turning a family switch off clears only that family

- **GIVEN** an account whose exclusion list contains one family's pattern and one unrelated custom pattern
- **WHEN** an operator turns that family's switch off
- **THEN** the dashboard saves an exclusion list containing only the custom pattern

#### Scenario: A custom pattern can be added and removed

- **WHEN** an operator enters a pattern that matches no family switch and confirms it
- **THEN** the editor renders that pattern as a removable chip
- **AND** activating that chip's remove control saves the exclusion list without that pattern

#### Scenario: Duplicate and blank patterns are ignored

- **WHEN** an operator submits a blank pattern, or a pattern already in the list ignoring case
- **THEN** the editor does not add a second entry

#### Scenario: A cc/-prefixed alias id is refused

- **WHEN** an operator submits a pattern beginning with `cc/`
- **THEN** the editor does not add it to the exclusion list
- **AND** the editor explains that CLIProxyAPI wire ids are required

### Requirement: Excluded-models editor honors the read-availability state

The excluded-models editor MUST render according to the account's `excludedModelsState` and MUST NOT claim a read succeeded when it did not, nor claim a failure when there was none. When the state is `available` the editor is fully interactive. When it is `unreadable` the editor MUST disable every switch, chip, and input and show a read-failure alert, because saving the list shown would overwrite exclusions the operator set by hand. When it is `unsupported` the editor MUST be locked but presented neutrally as "not available for this row", making no failure claim.

#### Scenario: An unreadable account is locked and reports the failure

- **WHEN** the editor renders for an account whose `excludedModelsState` is `unreadable`
- **THEN** the editor disables its controls
- **AND** the editor states that the exclusion list could not be read

#### Scenario: An unsupported row is locked without a failure claim

- **WHEN** the editor renders for an account whose `excludedModelsState` is `unsupported`
- **THEN** the editor disables its controls
- **AND** the editor does not render a read-failure alert

### Requirement: Excluded-models editing surfaces

The Settings CLIProxyAPI routing section MUST render the excluded-models editor on each Claude account row alongside that row's pause control, and the Accounts Claude detail view MUST render the same editor for each sidecar auth account. Both editors MUST be disabled while a routing mutation is in flight. The dashboard Claude account card MUST render the account's current exclusions compactly, using the family label when a pattern belongs to a known family and the raw pattern otherwise, and MUST offer an editing control even when the list is empty. The dashboard Claude list row MUST summarize the exclusions in its existing subtitle area rather than adding a column.

#### Scenario: Settings routing row exposes the editor

- **WHEN** the Settings CLIProxyAPI routing section renders a Claude account row
- **THEN** that row renders the excluded-models editor for that account

#### Scenario: Accounts detail exposes the editor

- **WHEN** the Accounts Claude detail view renders a sidecar auth account
- **THEN** that account renders the excluded-models editor

#### Scenario: Dashboard card shows exclusion badges

- **WHEN** the dashboard card view renders a Claude sidecar auth account whose exclusion list contains a known family's pattern
- **THEN** the card renders a compact badge labeled with that family

#### Scenario: Dashboard card without exclusions shows no badges

- **WHEN** the dashboard card view renders a Claude sidecar auth account with an empty exclusion list
- **THEN** the card renders no exclusion badge
- **AND** the card still offers a control for editing exclusions

#### Scenario: Dashboard list row summarizes exclusions inline

- **WHEN** the dashboard list view renders a Claude sidecar auth account with a non-empty exclusion list
- **THEN** the row summarizes those exclusions in its existing subtitle area
