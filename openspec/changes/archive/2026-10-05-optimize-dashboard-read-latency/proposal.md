## Why

A dashboard refresh on a production-sized SQLite store (about 245k request
logs, 200k Claude sidecar usage events, 360k usage-history rows) stayed on
loading for 12-20 seconds. Three reads dominated:

- `GET /api/request-logs/options` (the default all-time filter panel) took
  about 11 seconds. SQLite's planner chose the `deleted_at` index for every
  skip-scan probe, so each probe became a full pass over `request_logs`.
- `GET /api/dashboard/overview` and `GET /api/accounts` took 3.5-4 seconds
  each, almost all of it materializing the seven-day Claude sidecar usage-event
  window (64k ORM rows) on the event loop to compute quota estimates, which
  also stalled every other request in flight.
- The synthetic sidecar account cards re-ran an all-time per-source aggregate
  over `request_logs` on every load.

The SQLite bulk usage-history cache behind projections also kept every row
since its first fill, so its per-hit digest validation grew with uptime.

## What Changes

- On SQLite, unfiltered facet probes disqualify the baseline filters from index
  selection, so every probe seeks the facet column's own index.
- A process-wide cache holds the Claude sidecar usage-event window the quota
  estimates read. It fetches only rows above its id watermark, validates the
  window with a count/max-id fingerprint, and reloads on any mismatch. The usage
  collector refreshes it after each drain, so reads find it current.
- Quota-estimate window math uses sorted arrays and bisection instead of
  repeated passes over the event history; results are unchanged.
- Per-source request-usage totals for synthetic sidecar accounts share the
  existing request-usage summary cache (same TTL and invalidation).
- The SQLite bulk usage-history cache prunes rows that fell behind the sliding
  window.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `query-caching`: unfiltered facet probes seek the facet index on SQLite;
  Claude quota estimates read a cached usage-event window; per-source sidecar
  usage totals are cached with the account summaries; the SQLite bulk
  usage-history cache window slides.

## Impact

- `app/modules/request_logs/repository.py`
- `app/modules/claude_sidecar/usage_event_cache.py` (new),
  `usage_repository.py`, `usage_estimates.py`, `usage_collector.py`,
  `service.py`
- `app/modules/accounts/repository.py`, `app/modules/accounts/service.py`,
  `app/modules/dashboard/service.py`
- `app/modules/usage/repository.py`

No API, schema, migration, or dashboard UI change. Response payloads are
unchanged except that synthetic sidecar lifetime totals may lag by up to the
existing summary-cache TTL (30 seconds), as per-account totals already do.
