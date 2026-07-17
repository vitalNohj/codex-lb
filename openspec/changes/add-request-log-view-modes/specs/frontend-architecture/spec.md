## ADDED Requirements

### Requirement: Dashboard request logs support simplified and expanded table views
The dashboard Request Logs section SHALL allow operators to select `Simplified` or `Expanded` table presentation. The default presentation SHALL be `Simplified`. The selected presentation SHALL persist locally and apply on later dashboard visits in the same browser profile.

The Simplified presentation MUST render Time, Account, API Key, Model, Tokens, Cost, Status, and Details columns. It MUST render the persisted plan tier within the Account cell and MUST omit standalone Plan, Transport, TTFT, and TPS columns.

The Expanded presentation MUST render Time, Account, Plan, API Key, Model, Transport, Status, TTFT, TPS, Tokens, Cost, and Details columns. Both presentations MUST use the same filtered and paginated request-log collection and MUST open the same complete Request Details dialog.

#### Scenario: Request logs default to simplified presentation
- **WHEN** the request-log view preference is unset or invalid
- **THEN** the Request Logs section renders the Simplified presentation
- **AND** the view control indicates `Simplified` is selected
- **AND** the table renders the eight simplified columns

#### Scenario: Simplified presentation keeps plan with account
- **WHEN** a request-log row with a persisted plan tier renders in Simplified presentation
- **THEN** the plan tier is visible within the Account cell
- **AND** the table does not render standalone Plan, Transport, TTFT, or TPS columns

#### Scenario: Operator selects expanded presentation
- **WHEN** an operator selects `Expanded`
- **THEN** the table renders the twelve expanded columns
- **AND** Transport, TTFT, and TPS values are visible when their request-log fields are available
- **AND** the filtered rows and pagination state do not change

#### Scenario: Request-log view preference persists locally
- **WHEN** an operator selects `Expanded`
- **AND** later returns to the dashboard in the same browser profile
- **THEN** the Request Logs section renders the Expanded presentation without another selection

#### Scenario: Request details remain complete in simplified presentation
- **WHEN** an operator opens Request Details from a Simplified row
- **THEN** the dialog exposes the same request metadata as it does from Expanded presentation
- **AND** omitted table fields such as Transport, TTFT, Queue, and TPS remain available in the dialog
