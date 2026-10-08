## ADDED Requirements

### Requirement: Retained OAuth usage expires at its reset time

A retained Claude OAuth usage bucket (`five_hour` or `seven_day`) whose `resets_at` is at or before now MUST NOT supply that window's remaining percent or reset time. Codex-lb MUST estimate that window from usage queue events at or after the bucket's `resets_at`. When either bucket has expired, the auth's usage source MUST be `usage_queue` and its confidence MUST NOT be `oauth`.

#### Scenario: Weekly reset passes while OAuth usage fetches fail

- **GIVEN** the latest snapshot retains OAuth usage for an auth with 2% weekly remaining and a weekly `resets_at` one hour ago
- **AND** the auth has a 700-token weekly budget, 686 tokens of usage before the reset, and 7 tokens after it
- **WHEN** an authenticated dashboard operator calls `GET /api/claude-sidecar/quota`, `GET /api/accounts`, or `GET /api/dashboard/overview`
- **THEN** the auth's weekly remaining percent is 99 and its weekly used tokens are 7
- **AND** its weekly reset time is seven days after the first post-reset event
- **AND** its usage source is `usage_queue` and its confidence is `estimated`

#### Scenario: Expired window without a plan budget

- **GIVEN** the latest snapshot retains OAuth usage for an auth whose buckets have both reset
- **AND** no plan budget is configured for that auth
- **WHEN** codex-lb builds the usage estimates
- **THEN** the auth's remaining percentages and reset times are null
- **AND** its confidence is `unknown`

#### Scenario: Only the five-hour bucket has reset

- **GIVEN** the latest snapshot retains OAuth usage for an auth whose five-hour `resets_at` has passed and whose weekly `resets_at` has not
- **WHEN** codex-lb builds the usage estimates
- **THEN** the auth's five-hour values come from usage queue records since the five-hour reset
- **AND** its weekly remaining percent and reset time come from the OAuth bucket
- **AND** its confidence is not `oauth`

#### Scenario: Bucket without a reset time stays authoritative

- **GIVEN** the latest snapshot retains OAuth usage for an auth whose buckets have no `resets_at`
- **WHEN** codex-lb builds the usage estimates
- **THEN** the auth uses the OAuth remaining percentages
- **AND** its confidence is `oauth`
