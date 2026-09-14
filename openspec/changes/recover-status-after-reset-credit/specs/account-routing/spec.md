## MODIFIED Requirements

### Requirement: Rate-limit cooldowns are enforced across replicas

A replica that did not observe the upstream 429 MUST NOT transition a
`RATE_LIMITED` account to `ACTIVE` while the persisted `reset_at` deadline is
in the future, regardless of the account's recorded usage. For `RATE_LIMITED`
rows with `blocked_at` set but no persisted `reset_at` (legacy rows written
before cooldown persistence), replicas MUST hold the account `RATE_LIMITED`
until at least `blocked_at + RATE_LIMITED_MIN_COOLDOWN_SECONDS`. Recovery
transitions MUST be written through the compare-and-set status update
(`update_status_if_current`) so a stale snapshot cannot clobber a newer
marking.

This constraint applies to every recovery path that writes account status,
including the usage-refresh reconcile path: a usage refresh that observes
available quota for a `RATE_LIMITED` account with `blocked_at` set MUST NOT
rewrite the account to `ACTIVE` (or clear `reset_at`/`blocked_at`) while the
persisted cooldown deadline — `reset_at`, or the
`blocked_at + RATE_LIMITED_MIN_COOLDOWN_SECONDS` floor when `reset_at` is
NULL — is still in the future. Only the replica that observed the 429 MAY
recover the account earlier, through its runtime-cooldown-gated fresh-usage
path; a replica's runtime cooldown state counts as observing the current 429
only when its runtime block marker is at least as recent as the effective
persisted `blocked_at` — leftover runtime state from an earlier 429 MUST NOT
unlock early recovery of a newer block. `RATE_LIMITED` rows without
`blocked_at` (stale window-derived markings) keep the existing fresh-usage
recovery.

A successful reset-credit consume is operator-and-upstream proof that the
blocked window was reset. The forced usage refresh that follows that consume
MUST be allowed to recover the account to `ACTIVE` before the persisted
cooldown elapses when the post-reset windows have available quota. Periodic
usage refresh without that consume MUST keep the cooldown hold.

#### Scenario: Usage refresh does not clear a running Retry-After cooldown

- **GIVEN** an account marked `RATE_LIMITED` by a 429 whose Retry-After hint persisted `reset_at` 20 minutes in the future and `blocked_at` set
- **WHEN** a periodic usage refresh fetches fresh usage showing available quota before that deadline
- **THEN** the persisted row keeps status `RATE_LIMITED` with its `reset_at` and `blocked_at` intact
- **AND** once the deadline elapses, a later refresh may recover the account to `ACTIVE` through the compare-and-set path

#### Scenario: Peer replica does not flip a cooling account back

- **GIVEN** balancer instance A marked account X `RATE_LIMITED` from a 429 with no reset metadata
- **AND** account X's recorded usage is below 100%
- **WHEN** a second balancer instance sharing the same database runs account selection
- **THEN** account X is not selected
- **AND** the persisted row remains `RATE_LIMITED` with its `reset_at` deadline intact until the deadline elapses

#### Scenario: Stale runtime cooldown does not unlock early recovery of a newer block

- **GIVEN** a replica holds expired runtime cooldown state left over from an earlier 429 of account X
- **AND** account X was since re-marked `RATE_LIMITED` by a peer replica with a newer `blocked_at` and a future persisted `reset_at`
- **WHEN** the replica evaluates account X with usage recorded after the newer `blocked_at`
- **THEN** account X stays `RATE_LIMITED` and is not selected until the persisted deadline elapses

#### Scenario: Legacy row without reset_at is floored

- **GIVEN** a persisted `RATE_LIMITED` row with `blocked_at` five seconds ago and `reset_at` NULL
- **WHEN** a fresh balancer instance evaluates it during selection
- **THEN** the account stays `RATE_LIMITED` and is not selected

#### Scenario: Reset-credit consume recovers before the persisted 429 deadline

- **GIVEN** an account marked `RATE_LIMITED` by a 429 whose persisted `reset_at` is still in the future
- **AND** a reset-credit consume for that account succeeds
- **AND** the following forced usage refresh writes available quota on the post-reset windows
- **THEN** the persisted row is marked `ACTIVE`
- **AND** `reset_at` and `blocked_at` are cleared
