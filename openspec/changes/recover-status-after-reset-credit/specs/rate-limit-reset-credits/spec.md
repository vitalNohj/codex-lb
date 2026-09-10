## ADDED Requirements

### Requirement: Successful reset-credit consume recovers blocked account status

After a successful reset-credit consume the system MUST force-refresh that account's usage and MUST recover a `rate_limited` or `quota_exceeded` account to `active` when the post-reset windows report available quota, even if a persisted 429 `blocked_at`/`reset_at` cooldown is still in the future. The consume itself is proof the blocked window was reset. Exhausted post-reset windows MUST remain blocked. Periodic usage refresh MUST keep honoring the persisted cooldown when no reset-credit consume authorized recovery.

#### Scenario: Rate-limited Plus account recovers after reset credit

- **GIVEN** an account is persisted as `rate_limited` with `blocked_at` set and `reset_at` days in the future
- **AND** the operator or API successfully consumes a reset credit for that account
- **AND** the following usage refresh writes primary and weekly usage below `100%`
- **THEN** the account is marked `active`
- **AND** persisted `reset_at` and `blocked_at` are cleared

#### Scenario: Exhausted weekly window stays blocked after reset credit

- **GIVEN** an account is persisted as `rate_limited` with a future cooldown deadline
- **AND** a reset-credit consume succeeds
- **AND** the following usage refresh writes weekly usage at `100%`
- **THEN** the account stays `rate_limited`

#### Scenario: Periodic refresh still honors a running 429 cooldown

- **GIVEN** an account is persisted as `rate_limited` with `blocked_at` set and `reset_at` still in the future
- **AND** no reset-credit consume has authorized recovery
- **WHEN** a periodic usage refresh fetches usage below `100%`
- **THEN** the persisted row stays `rate_limited` with its cooldown markers intact
