## 1. Handoff

- [x] 1.1 Wait until a committed drain is within half a second of expiring.
- [x] 1.2 Yield `503 service unavailable` from the Claude chat keepalive wrapper and close the upstream iterator.
- [x] 1.3 Leave streams that do not opt in, and streams while shutdown is not committed, unchanged.

## 2. Validation

- [x] 2.1 `openspec validate handoff-shutdown-stream-retry --strict`
- [x] 2.2 Unit tests cover the handoff frame and the not-yet-committed path.
