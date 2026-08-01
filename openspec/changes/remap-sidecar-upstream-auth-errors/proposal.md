## Why

OmniRoute (and other sidecar) upstreams sometimes return HTTP 401 with messages like `Missing API key` when their free-tier / provider credentials are exhausted or rejected. codex-lb already authenticated the client API key before sidecar dispatch, then passthroughs that upstream 401 to the client. Clients treat 401 as "your credentials are bad" and abort the session instead of retrying. Native Codex pool exhaustion already returns retryable 503 (`no_accounts`); sidecar upstream auth failures must do the same.

## What Changes

- Remap sidecar upstream HTTP 401/403 responses to client-facing **503** with `Retry-After` once client auth has already succeeded.
- Replace misleading upstream auth messages (e.g. `[401]: Missing API key`) in the client error envelope with a transient upstream-unavailable message; preserve the original upstream text in request logs for operators.
- Apply consistently on chat-completions (non-stream JSON + stream SSE) and OmniRoute Responses sidecar paths for CLIProxyAPI / OpenRouter / OmniRoute / Ollama dispatches.

## Capabilities

### New Capabilities

<!-- none -->

### Modified Capabilities

- `chat-completions-compat`: Sidecar upstream 401/403 must surface as retryable 503 with `Retry-After`, not as client auth failures.

## Impact

- `app/modules/proxy/*_sidecar_dispatch.py` (and OmniRoute Responses path)
- Shared helper for status/message remapping
- Unit tests covering non-stream status + stream SSE envelope
- Request-log `error_message` keeps original upstream text; client HTTP status / SSE envelope change
