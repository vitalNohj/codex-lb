## ADDED Requirements

### Requirement: Warm HTTP bridge stream reacquisition honors dashboard caps

When an idle HTTP bridge reacquires its account stream lease, the proxy MUST derive its account concurrency caps from the dashboard settings snapshot with the same precedence and partitioning as initial selection. This MUST apply to keyed and unkeyed sessions and to lock-free callers that already supply a fair-share threshold. Settings-cache reads needed for reacquisition MUST resolve before acquiring the session pending lock. A session that already holds its stream lease MUST NOT require a settings read solely to admit another turn.

#### Scenario: Unlimited dashboard stream cap overrides a finite startup limit

- **GIVEN** the startup account stream limit is 1 and the dashboard account stream limit is 0 (unlimited)
- **AND** the warm session account already has 2 in-flight streams
- **WHEN** the idle session reacquires its stream lease
- **THEN** the account stream cap admits the lease without `account_stream_cap`

#### Scenario: A stricter dashboard stream cap is enforced

- **GIVEN** the startup account stream limit is 8 and the dashboard account stream limit is 1
- **WHEN** the warm session account has one in-flight stream and reacquires another stream lease
- **THEN** admission fails with HTTP 429 and `account_stream_cap`
- **AND** no new lease is installed or counted

#### Scenario: A settings refresh does not block session bookkeeping

- **GIVEN** a keyed or unkeyed idle session needs its next stream lease
- **WHEN** the cached dashboard settings refresh stalls
- **THEN** the session pending lock remains available to other work
