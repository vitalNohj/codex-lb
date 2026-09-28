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
- **WHEN** a reset-credit consume force-refreshes that account and the persisted clear succeeds
- **THEN** persisted `blocked_at` is cleared
- **AND** the in-process rate-limit runtime markers for that waived block are cleared

### Requirement: Newer rate limits survive a missed reset-credit waiver

A reset-credit forced refresh MUST drop in-process rate-limit markers only after the persisted block clear succeeds, and MUST leave a runtime marker whose `blocked_at` is newer than the waived marker in place. Runtime and persisted `blocked_at` MUST be compared at persisted whole-second precision, so the runtime copy of the waived 429 is not treated as newer because of its sub-second part.

#### Scenario: Missed waiver keeps the newer runtime marker

- **GIVEN** a reset-credit waiver whose compare-and-set misses because a newer 429 rewrote persisted `blocked_at`
- **WHEN** the forced refresh finishes the waiver
- **THEN** that account's in-process rate-limit markers are left unchanged

#### Scenario: Successful waiver keeps a newer runtime marker

- **GIVEN** a reset-credit waiver that cleared persisted `blocked_at`
- **AND** this process holds a runtime `blocked_at` newer than the waived marker
- **WHEN** the forced refresh drops in-process markers
- **THEN** that newer runtime marker stays

#### Scenario: Successful waiver clears the same 429 recorded with sub-second precision

- **GIVEN** a reset-credit waiver that cleared persisted `blocked_at` of whole second T
- **AND** this process holds a runtime `blocked_at` of T plus a fraction of a second for the same 429
- **WHEN** the forced refresh drops in-process markers
- **THEN** that runtime marker is cleared
