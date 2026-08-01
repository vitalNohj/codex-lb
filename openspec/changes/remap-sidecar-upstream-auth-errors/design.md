## Context

Live incident 2026-07-31: `opencode-zen/mimo-v2.5-free` via OmniRoute returned `[401]: Missing API key` after ~374 successes the same day. Client API key was valid (same key as adjacent 200s). OmniRoute `call_logs` show `provider=opencode-zen`, `account=noauth`, status 401. codex-lb passed `exc.status_code` through to the client. Native Codex accounts were all `rate_limited` the same window (`Model registry cleared because no active accounts remain`).

## Goals / Non-Goals

**Goals:**
- Client-facing status for sidecar upstream 401/403 becomes retryable 503 with `Retry-After`.
- Client-facing error message must not look like client auth failure (no bare `Missing API key` / `[401]: ...`).
- Operator request logs keep the original upstream message.

**Non-Goals:**
- Fixing opencode-zen free-tier credential pool health (upstream of OmniRoute).
- Changing true client-auth 401s from `ProxyAuthError` / `ApiKeyInvalidError` (those fire before sidecar dispatch).
- Adding pool-health headers/endpoints in this change.

## Decisions

1. **Shared remapper** in `app/modules/proxy/sidecar_upstream_errors.py` used by Claude / OpenRouter / OmniRoute / Ollama chat dispatches and OmniRoute Responses path.
2. **Remap only 401 and 403.** Other upstream codes keep current passthrough. 401/403 after client auth are always provider-side.
3. **Client status = 503** (match native `no_accounts`), not 429 — this is capacity/credential unavailability, not client rate limit.
4. **`Retry-After: 60`** (same constant pattern as opportunistic retry elsewhere).
5. **Stream path:** HTTP may already be 200 for SSE; rewrite the SSE error envelope message/code so clients that parse body text do not treat it as auth death.
6. **Log path:** `error_message` / `error_code` in request_logs keep original upstream text and existing `*_sidecar_error` code for triage.

## Risks / Trade-offs

- Genuine sidecar misconfiguration (wrong OmniRoute API key) also becomes 503. Acceptable: client auth already passed; operator sees original message in logs; 503 is still the right client signal vs session-killing 401.
- Clients that only inspect SSE body must see remapped message — status remap alone insufficient for stream.

## Migration Plan

None. Deploy with normal service restart when safe.
