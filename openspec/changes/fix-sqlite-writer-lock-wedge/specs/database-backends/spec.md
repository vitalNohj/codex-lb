## REMOVED Requirements

### Requirement: File-backed SQLite engines do not retain idle pooled descriptors

**Reason**: Stale since #177, which pooled file-SQLite connections. Replaced by the
requirement that file SQLite reuses a small pool whose checkout never waits.

**Migration**: None. No configuration changes; `database_pool_size` and
`database_max_overflow` still do not apply to file SQLite.

## ADDED Requirements

### Requirement: File-backed SQLite engines reuse a small pool whose checkout never waits

File-backed SQLite engines MUST retain a small fixed number of idle
connections for reuse, and a checkout MUST NOT wait for a connection or take a
process-wide lock. Pool sizing settings and the pool checkout timeout MUST NOT
apply to file SQLite. SQLite `:memory:` keeps its shared-engine behavior.

#### Scenario: File SQLite reuses a small pool that never waits

- **GIVEN** `database_url` resolves to a file-backed SQLite database
- **WHEN** the application creates its main or background async engine
- **THEN** the engine retains a small fixed number of idle connections
- **AND** its overflow is unbounded, so a checkout never waits for a return
- **AND** `database_pool_size`, `database_max_overflow`, and `pool_timeout` are not passed
- **AND** existing SQLite PRAGMAs and busy timeout behavior remain enabled

#### Scenario: A session held across a wait on another task does not wedge

- **GIVEN** a file-backed SQLite database
- **AND** a task holds an open session that has executed a statement
- **WHEN** that task awaits a second task that opens its own session and writes inside the shared SQLite writer section
- **THEN** the second task completes and the first task resumes
- **AND** this holds when the second task is a `run_if_leader` body

#### Scenario: PostgreSQL pooling is unchanged

- **GIVEN** `database_url` resolves to PostgreSQL
- **WHEN** the application creates its main or background async engine
- **THEN** PostgreSQL pool sizing, overflow, pre-ping, and recycle controls remain configured as before

## MODIFIED Requirements

### Requirement: SQLite account writes share the local writer section

SQLite account mutation paths SHALL enter the shared SQLite writer section
before performing database writes. This includes account import/upsert,
reauthentication upsert, token refresh persistence, status transitions,
account-level dashboard preference writes, and account deletion.

The shared SQLite writer section SHALL be held only around the write
transaction it protects. It SHALL NOT be taken by connection checkout or held
by an open session that is not writing.

PostgreSQL account mutation paths SHALL preserve their existing transaction and
advisory-lock behavior.

#### Scenario: Account token persistence is serialized on SQLite

- **GIVEN** the deployment uses a file-backed SQLite database
- **WHEN** an account token refresh persists new encrypted token values
- **THEN** the write executes inside the shared SQLite writer section

#### Scenario: Account status persistence is serialized on SQLite

- **GIVEN** the deployment uses a file-backed SQLite database
- **WHEN** an account status transition is persisted
- **THEN** the write executes inside the shared SQLite writer section

#### Scenario: Reads and idle sessions do not hold the writer section

- **GIVEN** the deployment uses a file-backed SQLite database
- **WHEN** a session checks out a connection, reads, or waits without writing
- **THEN** it does not hold the shared SQLite writer section
