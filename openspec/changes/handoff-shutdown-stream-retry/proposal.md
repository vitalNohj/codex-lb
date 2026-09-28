## Why

A service restart cancels in-flight Claude chat streams after the drain. The client sees the socket close, not an error it already retries. Pi then ends the turn and waits until someone types continue. Pi itself did not change.

## What Changes

- While process shutdown is committed and the drain is about to expire, a Claude chat stream emits one SSE error, `503 service unavailable`, and then ends
- That write happens before the connection is cancelled, so the client can retry onto the new process
- A client disconnect that is not process shutdown does not emit this error

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `chat-completions-compat`: a Claude sidecar chat stream MUST end a committed shutdown with the retryable SSE error `503 service unavailable`

## Impact

- Code: `app/core/shutdown.py`, `app/core/utils/sse.py`, `app/modules/proxy/claude_sidecar_dispatch.py`
- Tests: keepalive injection around a committed drain
- Live: takes effect on the next `codex-lb.service` restart. This change does not restart the service.
