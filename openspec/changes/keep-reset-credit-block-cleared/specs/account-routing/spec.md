## ADDED Requirements

### Requirement: Reset-credit block clears stay cleared

Account selection MUST NOT persist a runtime 429 `blocked_at` onto an account whose persisted `blocked_at` is already null. A reset-credit consume that cleared that marker MUST also drop the same account's in-process rate-limit runtime markers, so a later usage refresh can mark the account active once post-reset windows have available quota without waiting out the pre-reset `reset_at`. A row that still has persisted `blocked_at` set MUST keep that marker.

#### Scenario: Selection does not restore a waived block from runtime

- **GIVEN** an account marked `RATE_LIMITED` with a future `reset_at`
- **AND** persisted `blocked_at` is null after a reset-credit consume
- **AND** this process still holds the pre-reset 429 in runtime
- **WHEN** account selection evaluates the account
- **THEN** the evaluated state does not carry that runtime `blocked_at`
- **AND** selection does not write the pre-reset marker back onto the row

#### Scenario: Forced refresh drops the in-process rate-limit marker

- **GIVEN** an account marked `RATE_LIMITED` with persisted `blocked_at` set
- **WHEN** a reset-credit consume force-refreshes that account
- **THEN** persisted `blocked_at` is cleared
- **AND** the in-process rate-limit runtime markers for that account are cleared
