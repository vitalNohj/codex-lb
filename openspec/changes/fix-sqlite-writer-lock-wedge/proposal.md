## Why

#177 pooled the file-SQLite connection and took the process-wide SQLite
writer lock when a session checked out its connection, releasing it only on
checkin. A session held open while its task awaited another task that needed
the database deadlocked: the lock re-entered only for its owner task, and
`LeaderElection.run_if_leader` runs its body as a separate task. Production
wedged (HTTP accepted but never answered, `/health/live` included) within
minutes of the deploy.

## What Changes

- Connection checkout takes no lock and never waits. The shared SQLite writer
  section is a plain lock held only around each write transaction, as before
  #177.
- File-backed SQLite engines keep a small fixed number of reusable
  connections (WAL) with unbounded overflow, so connection reuse from #177
  stays while a checkout never waits for another session to return one.
- Regression tests: a session held while awaiting a task that needs a
  session, `run_if_leader` whose body opens a session while the caller holds
  one, and more held sessions than the pool retains.

## Capabilities

### Modified Capabilities
- database-backends: file-SQLite pooling and the writer-section scope.

## Impact

Only `app/db/session.py` pooling and writer-section code and their tests
change. The API key admission-write collapse from #177 is unchanged.
PostgreSQL is untouched.
