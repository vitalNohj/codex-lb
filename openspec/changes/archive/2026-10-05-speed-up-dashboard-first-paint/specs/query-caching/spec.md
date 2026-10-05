## MODIFIED Requirements

### Requirement: Dashboard overview memoizes per-account depletion EWMA state

`GET /api/dashboard/overview` MUST cache per-account EWMA depletion state in memory so repeated polls do not re-walk the full in-window `usage_history` slice in the depletion cache check when its content is unchanged. SQLite bulk history cache hits MUST avoid rebuilding or materializing the full cached history window when compact digest metadata proves older rows are unchanged; they MUST append newly inserted rows by monotonic row ID and reuse the cached grouped history for older rows. Repository-owned mutations that reassign or delete usage-history rows MUST clear the SQLite bulk history cache. Once a later request's `since` has advanced past the cached window start by more than a fixed slack, the cache entry MUST drop the rows behind the new `since` and validate only the remaining window from then on. On SQLite, `usage_history` MUST carry AFTER UPDATE and AFTER DELETE triggers that bump a single-row mutation generation; a cache hit whose generation is unchanged since its last validation, and whose cached range still matches the database's row count and max id, MUST be served without recomputing the content digest. A changed generation, or a store without both triggers and the generation row, MUST fall back to the content-digest validation. Projection history reads with a per-account row cap MUST return the same rows on SQLite as on PostgreSQL: rows at or after the per-account cutoff, every row at or after the uncapped recent floor, and the newest capped rows between them.

#### Scenario: Repeated polls with unchanged history reuse cached EWMA state
- **GIVEN** the dashboard service has previously computed depletion for an account
- **AND** a subsequent request supplies the same in-window history slice for that account with the same attached compact content signature
- **WHEN** depletion is recomputed for the dashboard response
- **THEN** the service MUST reuse the cached EWMA state for that account instead of replaying every history row
- **AND** the depletion metrics for that account MUST match the previously returned values for rate-bearing fields
- **AND** the cache hit check MUST use bounded signature metadata rather than building or retaining a per-row signature tuple
- **AND** the service MUST prune cached depletion state for account/window keys that are absent from the current dashboard history set

#### Scenario: Memoized EWMA state is invalidated when a new usage row is appended
- **WHEN** a later dashboard request supplies the same account's in-window history with an additional row appended (a new `recorded_at` past the previous latest)
- **THEN** the service MUST rebuild the EWMA state from the new history slice
- **AND** the recomputed rate MUST reflect the newly observed sample

#### Scenario: Memoized EWMA state is invalidated when an older row ages out of the window
- **WHEN** a later dashboard request supplies the same account's in-window history with the earliest row dropped (because it has aged past the window cutoff)
- **THEN** the service MUST rebuild the EWMA state from the narrowed history slice
- **AND** the cached state from the wider window MUST NOT influence the recomputed rate

#### Scenario: Memoized EWMA state is invalidated when an existing usage row is corrected
- **WHEN** a later dashboard request supplies the same account's in-window history with the same row count and endpoints but a corrected `used_percent`, `reset_at`, or `window_minutes` value on an existing row
- **THEN** the service MUST rebuild the EWMA state from the corrected history slice
- **AND** the recomputed rate-bearing metrics MUST reflect the corrected row content

#### Scenario: SQLite bulk history cache hit appends only new rows
- **GIVEN** a SQLite bulk usage-history query has already cached rows for an account/window set
- **WHEN** a later query uses a narrower `since` timestamp and the database only has new rows with IDs greater than the cached max ID
- **THEN** the repository fetches the new rows and appends them to the cached grouped history
- **AND** it does not materialize the older cached rows as snapshots when compact digest metadata proves they are unchanged

#### Scenario: Usage-history ownership mutation clears SQLite bulk history cache
- **WHEN** an account merge or delete operation updates or deletes `usage_history` rows
- **THEN** the repository clears the SQLite bulk history cache before serving future cached dashboard history reads

#### Scenario: SQLite bulk history cache window slides with the requested window
- **GIVEN** a SQLite bulk usage-history cache entry filled from an earlier `since`
- **WHEN** a later query's `since` is past the entry's window start by more than the prune slack
- **THEN** the entry MUST drop the rows recorded before the new `since` and adopt it as its window start
- **AND** a later same-id correction inside the remaining window MUST still invalidate the cached rows

#### Scenario: Unchanged mutation generation skips the content digest
- **GIVEN** a SQLite store with the usage-history mutation triggers and a cached bulk-history entry
- **WHEN** a later read finds the same generation and the same row count and max id for the cached range
- **THEN** the repository serves the cached rows without computing the content digest

#### Scenario: An in-place change or delete revalidates the cache
- **GIVEN** a cached bulk-history entry on a SQLite store with the mutation triggers
- **WHEN** a usage-history row in the cached range is updated or deleted
- **THEN** the next read observes a new generation and returns the database's current rows

#### Scenario: A row inserted below the cached max id is detected
- **GIVEN** a cached bulk-history entry
- **WHEN** a row is inserted with an id below the cached max id
- **THEN** the row-count check fails and the next read returns the inserted row

#### Scenario: SQLite applies the projection row cap
- **WHEN** projections read usage history with a per-account row cap and an uncapped recent floor on SQLite
- **THEN** each account's rows are those PostgreSQL's capped fetch would return, oldest first

### Requirement: Dashboard conversation trends aggregate by bucket

The dashboard conversation trend query MUST group by the configured time bucket
and count distinct non-empty normalized conversation IDs within each bucket. It
MUST exclude warmup traffic and MUST NOT use model or service-tier grouping that
could cause one conversation to be counted more than once in a bucket. For
hour-multiple display buckets the count MUST merge the conversation presence
rollup with the raw live tail through a UNION before the distinct count, so a
conversation appearing in both the folded segment and the raw tail of one
display bucket still counts once. The raw side MUST read `request_logs` as two `requested_at` ranges, the partial hour below the first whole folded hour and the tail from the watermark-clamped end, with the tail bound taken from the rollup state row in the same statement, so the read touches only un-folded rows instead of every row since the window start.

#### Scenario: One conversation across model groups counts once per bucket

- **GIVEN** a bucket contains two non-warmup request logs for `conv-a` under
  different models and one log for `conv-b`
- **WHEN** the dashboard conversation trend aggregate is calculated
- **THEN** that bucket's conversation count is `2`

#### Scenario: One conversation across the fold boundary counts once per bucket

- **GIVEN** a display bucket containing rows for `conv-a` below the
  conversation watermark (rollup-served) and above it (raw-served)
- **WHEN** the dashboard conversation trend aggregate is calculated
- **THEN** that bucket's conversation count counts `conv-a` once

#### Scenario: The raw tail read starts at the conversation watermark
- **GIVEN** a 30-day window whose conversation presence is folded through one hour ago
- **WHEN** the dashboard conversation metrics are calculated
- **THEN** the raw side reads only rows below the first whole folded hour and rows at or after the watermark
- **AND** the counts equal the unfolded raw computation

## ADDED Requirements

### Requirement: Dashboard sync status endpoint

The dashboard MUST expose `GET /api/dashboard/sync-status` behind the dashboard session, returning `{lastSyncAt}` computed exactly as the overview's `lastSyncAt` (the newest primary, secondary, monthly, or additional usage sample), without computing any other overview data.

#### Scenario: Sync status matches the overview
- **GIVEN** usage samples across primary, secondary, and monthly windows
- **WHEN** a client requests `GET /api/dashboard/sync-status`
- **THEN** `lastSyncAt` equals the overview's `lastSyncAt`
- **AND** it is `null` when no usage sample exists

### Requirement: Aggregate depletion picks the worst case deterministically

The aggregate depletion reported for a usage window MUST select the account with the highest risk and, among equal risk, the soonest projected exhaustion (accounts that do not exhaust before reset rank below any that do), then the highest burn rate, then the lowest safe-usage percent. The selection MUST NOT depend on the order accounts are iterated.

#### Scenario: Saturated risk ties resolve the same way every time
- **GIVEN** several accounts whose risk is saturated at 1.0 with different exhaustion times and safe lines
- **WHEN** projections are computed in any account order, or in processes with different hash seeds
- **THEN** the reported safe line, burn rate, and exhaustion time come from the same account every time
