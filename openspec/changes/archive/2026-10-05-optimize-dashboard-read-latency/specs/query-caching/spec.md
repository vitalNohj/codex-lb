## MODIFIED Requirements

### Requirement: Unfiltered request-log filter options avoid full DISTINCT passes

When `GET /api/request-logs/options` is requested without user-supplied filters, each facet (account ids, model/reasoning-effort pairs, api-key ids, status/error-code pairs) MUST be computed with loose-index-scan probes bounded by the facet's distinct-value count, not by the size of `request_logs`. The returned option sets, their ordering, and the soft-delete/status-facet semantics MUST be identical to the unbounded `DISTINCT` results. On SQLite, the baseline facet filters (soft-delete exclusion and the status allow-list) MUST be disqualified from index selection so that every probe seeks the facet column's own index instead of an index on a baseline-filter column.

#### Scenario: Unfiltered facets return identical option sets via bounded probes

- **GIVEN** request logs spanning multiple accounts, models with and without reasoning effort, api keys, and statuses with and without error codes
- **WHEN** the options endpoint is called with no filters
- **THEN** each facet MUST be produced by per-distinct-value index probes (recursive skip scan) rather than a full `DISTINCT` pass
- **AND** the response MUST equal the legacy `DISTINCT` results, including `(value, NULL)` pairs and ordering

#### Scenario: Soft-deleted rows stay excluded from skip-scanned facets

- **GIVEN** request-log rows with `deleted_at` set
- **WHEN** the options endpoint is called with no filters
- **THEN** values appearing only on soft-deleted rows MUST NOT appear in any facet

#### Scenario: SQLite probes seek the facet index rather than a baseline-filter index

- **GIVEN** a SQLite store
- **WHEN** the options endpoint is called with no filters
- **THEN** no skip-scan probe's query plan MUST search `request_logs` by `deleted_at`
- **AND** only the status facet and its error-code pair probes MAY search `request_logs` by `status`

### Requirement: Dashboard overview memoizes per-account depletion EWMA state

`GET /api/dashboard/overview` MUST cache per-account EWMA depletion state in memory so repeated polls do not re-walk the full in-window `usage_history` slice in the depletion cache check when its content is unchanged. SQLite bulk history cache hits MUST avoid rebuilding or materializing the full cached history window when compact digest metadata proves older rows are unchanged; they MUST append newly inserted rows by monotonic row ID and reuse the cached grouped history for older rows. Repository-owned mutations that reassign or delete usage-history rows MUST clear the SQLite bulk history cache. Once a later request's `since` has advanced past the cached window start by more than a fixed slack, the cache entry MUST drop the rows behind the new `since` and validate only the remaining window from then on.

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

## ADDED Requirements

### Requirement: Claude sidecar quota estimates read a cached usage-event window

Every read that builds Claude sidecar quota estimates (dashboard overview, accounts list, sidecar quota panel, pooled OAuth usage) MUST obtain the seven-day `claude_sidecar_usage_events` window from a process-wide in-memory cache rather than materializing the window per request. Each read MUST fetch only rows whose id exceeds the cache's watermark, MUST validate the cached window against a count and max-id fingerprint read in the same transaction, and MUST reload the whole window when the fingerprint disagrees. Reads MUST return exactly the events at or after the requested `since`, ordered by timestamp then id. The Claude sidecar usage collector MUST refresh the cache after each drain. Estimate results MUST be identical to computing them from a fresh read of the window.

#### Scenario: Appended events are fetched incrementally
- **GIVEN** the cache already holds the window
- **WHEN** new usage events are inserted, including one with an earlier timestamp than cached events
- **AND** an estimate read follows
- **THEN** the read MUST fetch only the rows above the watermark
- **AND** the returned events MUST include the new rows in timestamp order

#### Scenario: Rows missing from the store force a reload
- **GIVEN** the cache holds the window
- **WHEN** an event inside the window is deleted outside the cache's knowledge
- **AND** an estimate read follows
- **THEN** the fingerprint MUST disagree and the cache MUST reload the window
- **AND** the deleted event MUST NOT be returned

#### Scenario: A slightly earlier window start reuses the cache
- **GIVEN** the cache was synced for a window start computed moments later than the next reader's
- **WHEN** the next reader asks for a `since` within the cache's slack below its window start
- **THEN** the read MUST be served without fetching event rows
- **AND** it MUST include the events between the earlier `since` and the previous window start

### Requirement: Synthetic sidecar account usage totals share the request-usage summary cache

Per-source lifetime request-usage totals shown on synthetic sidecar account entries MUST be cached in the request-usage summary cache under a key space distinct from per-account summaries, with the same fixed TTL, generation fence, and invalidation as the per-account summaries. Account deletion and identity consolidation MUST clear them together with the per-account summaries.

#### Scenario: Per-source totals are served from cache within the TTL
- **GIVEN** per-source totals for a source set were computed
- **WHEN** a new request log for that source is written and the same source set is read again within the TTL
- **THEN** the cached totals MUST be returned
- **AND** reading a different source set MUST compute fresh totals
- **AND** clearing the request-usage summary cache MUST make the next read reflect the new log
