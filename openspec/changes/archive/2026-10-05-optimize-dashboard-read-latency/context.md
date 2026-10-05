## Measurements

Snapshot of the production SQLite store (2026-10-05): 245,803 request logs,
203,825 Claude sidecar usage events (64k inside the seven-day window), 362,526
usage-history rows. Requests served in-process against the snapshot; the
dashboard page-load sequence is overview, request logs, filter options, and
settings in parallel, then projections.

| Read | Before | After (warm) |
| --- | --- | --- |
| `GET /api/request-logs/options` (all time) | ~11.3 s | ~0.45 s |
| `GET /api/dashboard/overview` | ~4.0 s | ~0.7 s |
| `GET /api/accounts` | 3.5-5.6 s | ~0.4 s |
| Full page-load sequence | ~12.5 s | ~1.6 s |

The live instance also serves proxy traffic on the same event loop, which is
why the page took 20+ seconds there: the event-loop-bound estimate work
serialized with everything else.

## Why unary `+` on SQLite

The baseline facet filters (`deleted_at IS NULL`, the status allow-list) match
nearly every row, but without statistics SQLite prefers an equality-indexed
term over the facet column's index; with `ANALYZE` statistics it picks the
status index instead, which is no better. Unary `+` is SQLite's documented way
to disqualify a term from index selection without changing its value. The
probe then walks the facet index and filters the few rows it touches (9 s to
5 ms for the model facet). PostgreSQL has no unary `+` for booleans and needs
no hint, so it keeps the unwrapped conditions.

## Why an incremental event cache rather than a TTL

`claude_sidecar_usage_events` is append-only: the collector inserts and nothing
updates, and nothing deletes inside the window. An id watermark therefore finds
every new row, and a count/max-id fingerprint over the window, read in the same
transaction, catches anything else (manual deletes, restored backups, another
database). A TTL cache would still pay the full load on every expiry and serve
stale estimates in between; the incremental cache costs one covering-index
fingerprint query (about 10 ms) per read and is always current.

Readers compute their own `now`, so the cache keeps 15 minutes of rows below
the window; a reader a moment behind the last sync reuses the window instead of
forcing a reload.

## Bulk usage-history cache

The digest validation stays as is: sums-based fingerprints were rejected
earlier because offsetting corrections collide. Pruning keeps the validated
range at the requested window instead of everything since the first fill.
